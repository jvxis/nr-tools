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
    """Quebra em blocos <= max_len, preferindo quebras em '\\n'."""
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

# ========== DB QUERIES ==========
SQL_FORWARDS = """
SELECT chan_id_in, chan_id_out, amt_in_msat, amt_out_msat, fee, forward_date
FROM gui_forwards
WHERE forward_date BETWEEN ? AND ?
"""
SQL_CHAN_META = """
SELECT chan_id, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open
FROM gui_channels
"""
SQL_REBAL_PAYMENTS = """
SELECT value, fee, creation_date
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
    Usa SCID decimal como chave (lncli expõe 'scid').
    Se não houver 'scid', cai no 'chan_id' como backup.
    """
    data = json.loads(run(f"{LNCLI} listchannels"))
    snap = {}
    for ch in data.get("channels", []):
        key = str(ch.get("scid") or ch.get("chan_id"))  # preferir scid
        snap[key] = {
            "capacity": int(ch.get("capacity", 0)),
            "local_balance": int(ch.get("local_balance", 0)),
            "remote_balance": int(ch.get("remote_balance", 0)),
            "remote_pubkey": ch.get("remote_pubkey"),
            "chan_point": ch.get("channel_point"),
            "alias": ch.get("peer_alias", ""),  # ajuda para debug
        }
    return snap

# ========== AMBOSS ==========
def amboss_p65_incoming_ppm(pubkey, cache):
    """p65 do incoming_fee_rate_metrics/weighted_corrected_mean (7d). Cache 3h."""
    if not AMBOSS_TOKEN:
        return None  # sem token => sem seed Amboss

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
    cur.execute(SQL_CHAN_META)
    meta_rows = cur.fetchall()

    # Indexa meta por SCID (assumindo que gui_channels.chan_id = SCID decimal)
    channels_meta = {}
    open_scids = set()
    for (chan_id, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open) in meta_rows:
        scid = str(chan_id)  # LNDg normalmente guarda SCID decimal em gui_channels.chan_id
        channels_meta[scid] = {
            "alias": alias or "Unknown",
            "local_ppm": int(local_fee_rate or 0),
            "remote_fee_rate": int(remote_fee_rate or 0),
            "ar_max_cost": float(ar_max_cost or 0),
            "remote_pubkey": remote_pubkey,
            "is_open": int(is_open or 0),
        }
        if int(is_open or 0) == 1:
            open_scids.add(scid)

    # Snapshot vivo do LN (via lncli), indexado por SCID
    live = listchannels_snapshot()

    # ---- Forwards (7d) para métricas de saída e in-volume por peer ----
    cur.execute(SQL_FORWARDS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    rows = cur.fetchall()

    out_fee_sat = defaultdict(int)
    out_amt_sat = defaultdict(int)
    out_count   = defaultdict(int)

    # mapa SCID->pubkey a partir do snapshot vivo
    scid_pubkey = {}
    for scid, info in live.items():
        scid_pubkey[scid] = info.get("remote_pubkey")

    incoming_msat_by_pub = defaultdict(int)

    for (cid_in, cid_out, amt_in_msat, amt_out_msat, fee_sat, fwd_date) in rows:
        if cid_out:
            scid_out = str(cid_out)
            out_fee_sat[scid_out] += int(fee_sat or 0)
            out_amt_sat[scid_out] += int((amt_out_msat or 0)/1000)
            out_count[scid_out]   += 1
        if cid_in:
            scid_in = str(cid_in)
            pub = scid_pubkey.get(scid_in)
            if pub:
                incoming_msat_by_pub[pub] += int(amt_in_msat or 0)

    total_incoming_msat = sum(incoming_msat_by_pub.values())
    peer_count = max(1, len(incoming_msat_by_pub))
    avg_share = 1.0 / peer_count if peer_count > 0 else 0.0

    # ---- Custo de rebal (7d) via gui_payments ----
    cur.execute(SQL_REBAL_PAYMENTS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    pay_rows = cur.fetchall()
    rebal_value_sat = 0
    rebal_fee_sat   = 0
    for (value, fee, creation_date) in pay_rows:
        rebal_value_sat += int(value or 0)     # value em sat (LNDg)
        rebal_fee_sat   += int(fee or 0)       # fee em sat
    rebal_cost_ppm_7d = ppm(rebal_fee_sat, rebal_value_sat)  # custo usado no alvo

    report = []
    report.append(f"{'DRY-RUN ' if dry_run else ''}⚙️ AutoFee | janela {LOOKBACK_DAYS}d | rebal≈ {int(rebal_cost_ppm_7d)} ppm (gui_payments)")

    missing_live = 0

    for scid in sorted(open_scids):
        meta = channels_meta.get(scid, {})
        alias = meta.get("alias", "Unknown")
        local_ppm = meta.get("local_ppm", 0)

        live_info = live.get(scid)
        if not live_info:
            # SCID do DB não foi achado no lncli listchannels
            missing_live += 1
            out_ratio = 0.50  # fallback neutro
            pubkey = meta.get("remote_pubkey")
            cap = 0
            local_bal = 0
        else:
            pubkey = live_info.get("remote_pubkey") or meta.get("remote_pubkey")
            cap = int(live_info.get("capacity", 0))
            local_bal = int(live_info.get("local_balance", 0))
            out_ratio = (local_bal / cap) if cap > 0 else 0.50

        if not pubkey:
            # sem pubkey não dá pra setar fee
            report.append(f"⏭️  {alias} ({scid}) sem pubkey (ignorado)")
            continue

        if EXCLUSION_LIST and pubkey in EXCLUSION_LIST:
            report.append(f"⏭️  {alias} ({scid}) skip (exclusion)")
            continue

        out_ppm_7d = ppm(out_fee_sat.get(scid, 0), out_amt_sat.get(scid, 0))
        fwd_count  = out_count.get(scid, 0)

        # Seed Amboss (p65) do peer
        p65 = amboss_p65_incoming_ppm(pubkey, cache)
        if p65 is None:
            p65 = 200.0  # fallback conservador

        # Ponderação pelo volume de ENTRADA do peer
        if total_incoming_msat > 0 and VOLUME_WEIGHT_ALPHA > 0:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            factor = 1.0 + VOLUME_WEIGHT_ALPHA * (share - avg_share)
            p65 *= max(0.7, min(1.3, factor))

        # Alvo base
        target = p65 + rebal_cost_ppm_7d + COLCHAO_PPM

        # Liquidez
        if out_ratio < LOW_OUTBOUND_THRESH:
            target *= (1.0 + LOW_OUTBOUND_BUMP)
        elif out_ratio > HIGH_OUTBOUND_THRESH:
            target *= (1.0 - HIGH_OUTBOUND_CUT)
            if fwd_count == 0 and out_ratio > 0.60:
                target *= (1.0 - IDLE_EXTRA_CUT)

        target = clamp_ppm(target)

        # Circuit breaker
        state_all = state.get(scid, {})
        last_ppm  = state_all.get("last_ppm", local_ppm)
        last_dir  = state_all.get("last_dir", "flat")
        last_ts   = state_all.get("last_ts", 0)
        baseline  = state_all.get("baseline_fwd7d", None)

        new_ppm = target if local_ppm == 0 else apply_step_cap(local_ppm, target)

        now_ts = int(time.time())
        if last_dir == "up" and (now_ts - last_ts) <= CB_GRACE_DAYS*24*3600 and baseline:
            if baseline and baseline > 0 and fwd_count < baseline * CB_DROP_RATIO:
                new_ppm = clamp_ppm(int(new_ppm * (1.0 - CB_REDUCE_STEP)))
                report.append(f"🧯 CB: {alias} ({scid}) fwd {fwd_count}<{int(baseline*CB_DROP_RATIO)} ⇒ recuo {int(CB_REDUCE_STEP*100)}%")

        # Aplica/relata
        if new_ppm != local_ppm:
            if dry_run:
                action = f"DRY set {local_ppm}→{new_ppm} ppm"
            else:
                try:
                    bos_set_fee_ppm(pubkey, new_ppm)
                    action = f"set {local_ppm}→{new_ppm} ppm"
                    new_dir = "up" if new_ppm > local_ppm else ("down" if new_ppm < local_ppm else "flat")
                    state[scid] = {
                        "last_ppm": new_ppm,
                        "last_dir": new_dir,
                        "last_ts":  now_ts,
                        # baseline pós mudança: usa fwd_count atual como semente
                        "baseline_fwd7d": fwd_count if fwd_count > 0 else state_all.get("baseline_fwd7d", 0)
                    }
                except Exception as e:
                    action = f"❌ erro ao setar: {e}"
            report.append(f"✅ {alias}: {action} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{int(p65)}")
        else:
            report.append(f"🫤 {alias}: mantém {local_ppm} ppm | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)}")

    save_json(CACHE_PATH, cache)
    if not dry_run:
        save_json(STATE_PATH, state)

    msg = "\n".join(report)
    print(msg)

    # Só notifica no Telegram quando NÃO for dry-run
    if not dry_run:
        tg_send_big(msg)

    # Dica no final se faltou casar SCIDs
    if missing_live > 0:
        print(f"ℹ️  {missing_live} canal(is) não apareceram no lncli listchannels (out_ratio=0.50 por fallback). "
              f"Confirme LNCLI path/perm e se gui_channels.chan_id = SCID decimal.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto fee LND (Amboss seed, ponderação por entrada, liquidez e circuit-breaker)")
    parser.add_argument("--dry-run", action="store_true", help="Simula: não aplica BOS e não grava STATE; também não notifica no Telegram")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
