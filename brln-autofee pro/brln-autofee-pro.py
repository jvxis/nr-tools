#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, math, sqlite3, datetime, subprocess, argparse
from collections import defaultdict
import requests

# ========== CONFIG ==========
# ✅ CONFIRA ESTES PATHS:
DB_PATH = '/home/admin/lndg/data/db.sqlite3'   # caminho do banco do LNDg
LNCLI   = "lncli"                              # binário do lncli no PATH
BOS     = "/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/bos"  # bos completo

# Amboss (opcional; se vazio, usa fallback de seed)
AMBOSS_TOKEN = ""                               # <<< PREENCHER se quiser seed via Amboss
AMBOSS_URL   = "https://api.amboss.space/graphql"

# Telegram (opcional; só envia quando NÃO for --dry-run)
TELEGRAM_TOKEN = ""                             # <<< PREENCHER se quiser notificar
TELEGRAM_CHAT  = ""                             # <<< PREENCHER (id do chat/grupo)

LOOKBACK_DAYS = 7
CACHE_PATH    = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH    = "/home/admin/.cache/auto_fee_state.json"

# --- limites base ---
BASE_FEE_MSAT = 0
MIN_PPM = 150          # ↑ protege receita mínima
MAX_PPM = 2500

# --- “velocidade” de mudança por execução ---
STEP_CAP = 0.05        # ↓ muda no máx. 5% por rodada (era 0.20)

# --- colchão fixo no alvo ---
COLCHAO_PPM = 30       # ↓ menos agressivo que 50

# --- política de variação por liquidez (faixa morta: 5%–30%) ---
LOW_OUTBOUND_THRESH = 0.05   # <5% outbound = drenado ⇒ leve alta
HIGH_OUTBOUND_THRESH = 0.30  # >30% outbound = sobrando ⇒ leve queda
LOW_OUTBOUND_BUMP   = 0.05   # +5% no alvo quando <5%
HIGH_OUTBOUND_CUT   = 0.05   # -5% no alvo quando >30%
IDLE_EXTRA_CUT      = 0.01   # corte extra por ociosidade (bem conservador)

# --- peso do volume de ENTRADA do peer (Amboss) no alvo ---
VOLUME_WEIGHT_ALPHA = 0.10   # ↓ suaviza influência (era 0.30)

# --- circuit breaker (opcionalmente mais conservador) ---
CB_WINDOW_DAYS = 7
CB_DROP_RATIO  = 0.60   # ↑ só recua se os forwards caírem mais (era 0.50)
CB_REDUCE_STEP = 0.15
CB_GRACE_DAYS  = 10

# --- Proteção de custo de rebal (PISO) ---
REBAL_FLOOR_ENABLE = True     # habilita piso de segurança
REBAL_FLOOR_MARGIN = 0.10     # 10% acima do custo médio de rebal 7d

# Lista de exclusões (opcional). Deixe vazia ou adicione pubkeys para pular.
EXCLUSION_LIST = set()  # exemplo: {"02abc...", "03def..."}

# ========== HELPERS ==========
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)

def epoch_days_ago(days):
    t2 = int(time.time())
    return t2 - days*24*3600, t2

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except:
        pass
    return default

def to_sqlite_str(dt):
    """Converte datetime tz-aware para string ISO compatível com BETWEEN do SQLite."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat(sep=' ', timespec='seconds')

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)

def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"[cmd failed]\n{cmd}\n{p.stderr}")
    return p.stdout

def ppm(total_fee_sat, total_amt_sat):
    if total_amt_sat <= 0:
        return 0
    return (total_fee_sat / total_amt_sat) * 1_000_000

def clamp_ppm(v): return max(MIN_PPM, min(MAX_PPM, int(round(v))))
def fee_fraction(ppm_val): return ppm_val / 1_000_000.0

def apply_step_cap(current_ppm, target_ppm):
    if current_ppm <= 0:
        return clamp_ppm(target_ppm)
    delta = target_ppm - current_ppm
    cap = max(1, int(abs(current_ppm) * STEP_CAP))
    if delta > cap:  return current_ppm + cap
    if delta < -cap: return current_ppm - cap
    return target_ppm

def _chunk_text(text, max_len=4000):
    """Quebra em blocos <= max_len, preferindo quebras em '\n'."""
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks

def tg_send_big(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for part in _chunk_text(text, 4000):
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": part}, timeout=20)
            time.sleep(0.2)  # evita rate limit
        except Exception:
            pass

def has_column(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

# ========== DB QUERIES ==========
SQL_FORWARDS = """
SELECT chan_id_in, chan_id_out, amt_in_msat, amt_out_msat, fee, forward_date
FROM gui_forwards
WHERE forward_date BETWEEN ? AND ?
"""
# >>> inclui rebal_chan para piso por canal
SQL_REBAL_PAYMENTS = """
SELECT rebal_chan, value, fee, creation_date
FROM gui_payments
WHERE rebal_chan IS NOT NULL
  AND chan_out IS NOT NULL
  AND creation_date BETWEEN ? AND ?
"""

def db_connect():
    return sqlite3.connect(DB_PATH)

# ========== LND SNAPSHOT ==========
def listchannels_snapshot():
    """
    Indexa o snapshot do lncli de três formas:
      - by_scid_dec: usando 'scid' (decimal)  << MAIS CONFIÁVEL p/ cruzar com LNDg
      - by_cid_dec:  se 'chan_id' vier numérico (algumas versões antigas)
      - by_point:    sempre que houver 'channel_point'
    """
    data = json.loads(run(f"{LNCLI} listchannels"))
    by_scid_dec = {}
    by_cid_dec  = {}
    by_point    = {}
    for ch in data.get("channels", []):
        scid = ch.get("scid")        # decimal em string
        cid  = ch.get("chan_id")     # pode ser HEX em versões novas
        point = ch.get("channel_point")

        info = {
            "capacity": int(ch.get("capacity", 0)),
            "local_balance": int(ch.get("local_balance", 0)),
            "remote_balance": int(ch.get("remote_balance", 0)),
            "remote_pubkey": ch.get("remote_pubkey"),
            "chan_point": point,
        }
        if scid is not None and str(scid).isdigit():
            by_scid_dec[str(scid)] = info
        if cid is not None and str(cid).isdigit():
            by_cid_dec[str(cid)] = info
        if point:
            by_point[point] = info
    return {"by_scid_dec": by_scid_dec, "by_cid_dec": by_cid_dec, "by_point": by_point}

# ========== AMBOSS ==========
def amboss_p65_incoming_ppm(pubkey, cache):
    """p65 do incoming_fee_rate_metrics/weighted_corrected_mean (7d). Cache 3h."""
    key = f"incoming_p65_7d:{pubkey}"
    now = int(time.time())
    if key in cache and now - cache[key]["ts"] < 3*3600:
        return cache[key]["val"]

    from_date = (now_utc() - datetime.timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    q = {
        "query": """
        query GetNodeMetrics($from: String!, $metric: NodeMetricsKeys!, $pubkey: String!, $submetric: ChannelMetricsKeys) {
          getNodeMetrics(pubkey: $pubkey) {
            historical_series(from: $from, metric: $metric, submetric: $submetric)
          }
        }""",
        "variables": {
            "from": from_date,
            "metric": "incoming_fee_rate_metrics",
            "pubkey": pubkey,
            "submetric": "weighted_corrected_mean"
        }
    }
    headers = {"content-type":"application/json","Authorization": f"Bearer {AMBOSS_TOKEN}"}
    try:
        r = requests.post(AMBOSS_URL, headers=headers, json=q, timeout=20)
        r.raise_for_status()
        rows = r.json()["data"]["getNodeMetrics"]["historical_series"] or []
        vals = [float(v[1]) for v in rows if v and len(v)==2]
        if not vals:
            return None
        vals.sort()
        idx = int(0.65*(len(vals)-1))
        p65 = vals[idx]
        cache[key] = {"ts": now, "val": p65}
        return p65
    except Exception:
        return None

# ========== BOS ==========
def bos_set_fee_ppm(to_pubkey, ppm_value):
    # envia SEMPRE inteiro em PPM pro bos
    v = clamp_ppm(int(round(ppm_value)))
    cmd = f'{BOS} fees --to {to_pubkey} --set-fee-rate {v}'
    run(cmd)

# ========== STATE (CB) ==========
def get_state():
    return load_json(STATE_PATH, {})

def update_state(state, dry_run):
    if not dry_run:
        save_json(STATE_PATH, state)

# ========== PIPELINE ==========
def main(dry_run=False):
    cache = load_json(CACHE_PATH, {})
    state = get_state()

    t1_epoch, t2_epoch = epoch_days_ago(LOOKBACK_DAYS)
    start_dt = datetime.datetime.fromtimestamp(t1_epoch, datetime.timezone.utc)
    end_dt   = datetime.datetime.fromtimestamp(t2_epoch, datetime.timezone.utc)

    conn = db_connect()
    cur  = conn.cursor()

    # Detecta se 'chan_point' existe no LNDg
    if has_column(cur, "gui_channels", "chan_point"):
        cur.execute("""
            SELECT chan_id, chan_point, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open
            FROM gui_channels
        """)
        meta_rows = cur.fetchall()
        channels_meta = {}
        open_cids = set()
        for (chan_id, chan_point, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open) in meta_rows:
            cid = str(chan_id)  # este 'chan_id' do LNDg costuma ser SCID DECIMAL
            channels_meta[cid] = {
                "chan_point": chan_point,
                "alias": alias or "Unknown",
                "local_ppm": int(local_fee_rate or 0),
                "remote_fee_rate": int(remote_fee_rate or 0),
                "ar_max_cost": float(ar_max_cost or 0),
                "remote_pubkey": remote_pubkey,
                "is_open": int(is_open or 0),
            }
            if int(is_open or 0) == 1:
                open_cids.add(cid)
        has_chan_point = True
    else:
        cur.execute("""
            SELECT chan_id, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open
            FROM gui_channels
        """)
        meta_rows = cur.fetchall()
        channels_meta = {}
        open_cids = set()
        for (chan_id, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open) in meta_rows:
            cid = str(chan_id)  # ainda é SCID DECIMAL
            channels_meta[cid] = {
                "chan_point": None,
                "alias": alias or "Unknown",
                "local_ppm": int(local_fee_rate or 0),
                "remote_fee_rate": int(remote_fee_rate or 0),
                "ar_max_cost": float(ar_max_cost or 0),
                "remote_pubkey": remote_pubkey,
                "is_open": int(is_open or 0),
            }
            if int(is_open or 0) == 1:
                open_cids.add(cid)
        has_chan_point = False

    live = listchannels_snapshot()
    live_by_scid  = live["by_scid_dec"]
    live_by_cid   = live["by_cid_dec"]
    live_by_point = live["by_point"]

    # ---- Forwards (7d) para métricas de saída e in-volume por peer ----
    cur.execute(SQL_FORWARDS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    rows = cur.fetchall()

    out_fee_sat = defaultdict(int)
    out_amt_sat = defaultdict(int)
    out_count   = defaultdict(int)

    # Mapa cid(LNDg/SCID) -> pubkey
    chan_pubkey = {}
    for scid, info in live_by_scid.items():
        if info.get("remote_pubkey"):
            chan_pubkey[scid] = info.get("remote_pubkey")
    for cid, info in live_by_cid.items():
        if info.get("remote_pubkey") and cid not in chan_pubkey:
            chan_pubkey[cid] = info.get("remote_pubkey")
    for cid, meta in channels_meta.items():
        if cid not in chan_pubkey and meta.get("remote_pubkey"):
            chan_pubkey[cid] = meta.get("remote_pubkey")

    incoming_msat_by_pub = defaultdict(int)

    for (cid_in, cid_out, amt_in_msat, amt_out_msat, fee_sat, fwd_date) in rows:
        if cid_out:
            k = str(cid_out)
            out_fee_sat[k] += int(fee_sat or 0)
            out_amt_sat[k] += int((amt_out_msat or 0)/1000)
            out_count[k]   += 1
        if cid_in:
            k = str(cid_in)
            pub = chan_pubkey.get(k)
            if pub:
                incoming_msat_by_pub[pub] += int(amt_in_msat or 0)

    total_incoming_msat = sum(incoming_msat_by_pub.values())
    peer_count = max(1, len(incoming_msat_by_pub))
    avg_share = 1.0 / peer_count if peer_count > 0 else 0.0

    # ---- Custo de rebal verdadeiro (7d) via gui_payments ----
    cur.execute(SQL_REBAL_PAYMENTS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    pay_rows = cur.fetchall()

    # Global
    rebal_value_sat_global = 0
    rebal_fee_sat_global   = 0

    # Por canal (key = rebal_chan, esperado como SCID decimal do LNDg)
    perchan_value_sat = defaultdict(int)
    perchan_fee_sat   = defaultdict(int)

    for (rebal_chan, value, fee, creation_date) in pay_rows:
        v = int(value or 0)
        f = int(fee or 0)
        rebal_value_sat_global += v
        rebal_fee_sat_global   += f
        if rebal_chan is not None:
            perchan_value_sat[str(rebal_chan)] += v
            perchan_fee_sat[str(rebal_chan)]   += f

    rebal_cost_ppm_global = ppm(rebal_fee_sat_global, rebal_value_sat_global)
    # mapa canal->ppm
    rebal_cost_ppm_by_chan = {
        cid: ppm(perchan_fee_sat[cid], perchan_value_sat[cid]) for cid in perchan_value_sat.keys()
    }

    report = []
    report.append(f"{'DRY-RUN ' if dry_run else ''}⚙️ AutoFee | janela {LOOKBACK_DAYS}d | rebal≈ {int(rebal_cost_ppm_global)} ppm (gui_payments)")

    unmatched = 0

    for cid in sorted(open_cids):
        meta = channels_meta.get(cid, {})
        alias = meta.get("alias", "Unknown")
        local_ppm = meta.get("local_ppm", 0)

        # encontra o snapshot correto
        live_info = live_by_scid.get(cid)
        if (not live_info) and has_chan_point:
            cp = meta.get("chan_point")
            if cp:
                live_info = live_by_point.get(cp)
        if (not live_info):
            live_info = live_by_cid.get(cid)

        pubkey = (live_info or {}).get("remote_pubkey") or meta.get("remote_pubkey")
        if not pubkey:
            unmatched += 1
        if pubkey in EXCLUSION_LIST:
            report.append(f"⏭️  {alias} ({cid}) skip (exclusion)")
            continue

        cap   = int((live_info or {}).get("capacity", 0))
        local = int((live_info or {}).get("local_balance", 0))
        out_ratio = (local / cap) if cap > 0 else 0.5

        out_ppm_7d = ppm(out_fee_sat.get(cid, 0), out_amt_sat.get(cid, 0))
        fwd_count  = out_count.get(cid, 0)

        # Seed Amboss (p65) do peer
        p65 = amboss_p65_incoming_ppm(pubkey, cache) if pubkey else None
        if p65 is None:
            p65 = 200.0  # fallback conservador

        # Ponderação pelo volume de ENTRADA do peer
        if total_incoming_msat > 0 and VOLUME_WEIGHT_ALPHA > 0 and pubkey:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            factor = 1.0 + VOLUME_WEIGHT_ALPHA * (share - avg_share)
            p65 *= max(0.7, min(1.3, factor))

        # Alvo base
        target = p65 + rebal_cost_ppm_global + COLCHAO_PPM

        # Liquidez
        if out_ratio < LOW_OUTBOUND_THRESH:
            target *= (1.0 + LOW_OUTBOUND_BUMP)
        elif out_ratio > HIGH_OUTBOUND_THRESH:
            target *= (1.0 - HIGH_OUTBOUND_CUT)
            if fwd_count == 0 and out_ratio > 0.60:
                target *= (1.0 - IDLE_EXTRA_CUT)

        target = clamp_ppm(target)

        # Circuit breaker
        state_all = state.get(cid, {})
        last_ppm  = state_all.get("last_ppm", local_ppm)
        last_dir  = state_all.get("last_dir", "flat")
        last_ts   = state_all.get("last_ts", 0)
        baseline  = state_all.get("baseline_fwd7d", None)

        new_ppm = target if local_ppm == 0 else apply_step_cap(local_ppm, target)

        now_ts = int(time.time())
        if last_dir == "up" and (now_ts - last_ts) <= CB_GRACE_DAYS*24*3600 and baseline:
            if baseline > 0 and fwd_count < baseline * CB_DROP_RATIO:
                new_ppm = clamp_ppm(int(new_ppm * (1.0 - CB_REDUCE_STEP)))
                report.append(f"🧯 CB: {alias} ({cid}) fwd {fwd_count}<{int(baseline*CB_DROP_RATIO)} ⇒ recuo {int(CB_REDUCE_STEP*100)}%")

        # Piso de rebal por canal (fallback para global)
        if REBAL_FLOOR_ENABLE:
            ch_rebal_ppm = rebal_cost_ppm_by_chan.get(cid)
            if ch_rebal_ppm and ch_rebal_ppm > 0:
                floor_ppm = clamp_ppm(math.ceil(ch_rebal_ppm * (1.0 + REBAL_FLOOR_MARGIN)))
            elif rebal_cost_ppm_global > 0:
                floor_ppm = clamp_ppm(math.ceil(rebal_cost_ppm_global * (1.0 + REBAL_FLOOR_MARGIN)))
            else:
                floor_ppm = MIN_PPM
        else:
            floor_ppm = MIN_PPM

        new_ppm = max(new_ppm, floor_ppm)

        # Aplica/relata
        if new_ppm != local_ppm:
            if dry_run:
                action = f"DRY set {local_ppm}→{new_ppm} ppm"
            else:
                try:
                    if pubkey:
                        bos_set_fee_ppm(pubkey, new_ppm)
                        action = f"set {local_ppm}→{new_ppm} ppm"
                        new_dir = "up" if new_ppm > local_ppm else ("down" if new_ppm < local_ppm else "flat")
                        state[cid] = {
                            "last_ppm": new_ppm,
                            "last_dir": new_dir,
                            "last_ts":  now_ts,
                            "baseline_fwd7d": fwd_count if fwd_count > 0 else state_all.get("baseline_fwd7d", 0)
                        }
                    else:
                        action = "❌ sem pubkey/snapshot p/ aplicar"
                except Exception as e:
                    action = f"❌ erro ao setar: {e}"
            report.append(
                f"✅ {alias}: {action} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{int(p65)} | floor≥{floor_ppm}"
            )
        else:
            report.append(
                f"🫤 {alias}: mantém {local_ppm} ppm | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | floor≥{floor_ppm}"
            )

    if unmatched > 0:
        report.append(f"ℹ️  {unmatched} canal(is) sem snapshot por scid/chan_point (out_ratio=0.50 por fallback). Cheque versão do lncli e permissões.")

    save_json(CACHE_PATH, cache)
    if not dry_run:
        save_json(STATE_PATH, state)

    msg = "\n".join(report)
    print(msg)
    if not dry_run:            # não envia quando for --dry-run
        tg_send_big(msg)       # envia quebrado em blocos de ~4000 chars

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto fee LND (Amboss seed, ponderação por entrada, liquidez, piso de rebal por canal e circuit-breaker)")
    parser.add_argument("--dry-run", action="store_true", help="Simula: não aplica BOS e não grava STATE")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

