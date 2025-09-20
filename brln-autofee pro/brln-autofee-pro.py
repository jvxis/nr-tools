#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, math, sqlite3, datetime, subprocess, argparse
from collections import defaultdict
import requests

# ========== CONFIG ==========
DB_PATH = '/home/admin/lndg/data/db.sqlite3'   # ⚠️ CONFIRA caminho do SQLite do LNDg
LNCLI   = "lncli"                               # ⚠️ CONFIRA (ex.: "lncli" ou wrapper específico)
BOS     = "/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/bos"  # ⚠️ CONFIRA

# Amboss (preencher para ativar seed de incoming fee)
AMBOSS_TOKEN = ""                                # ⚠️ PREENCHA com seu token (ou deixe vazio p/ desativar)
AMBOSS_URL   = "https://api.amboss.space/graphql"

# Telegram (opcional: notificação do relatório quando NÃO for --dry-run)
TELEGRAM_TOKEN = ""                              # ⚠️ PREENCHA (ou deixe vazio p/ desativar)
TELEGRAM_CHAT  = ""                              # ⚠️ PREENCHA (ou deixe vazio p/ desativar)

# Janela padrão
LOOKBACK_DAYS = 7
CACHE_PATH    = "/home/admin/.cache/auto_fee_amboss.json"   # cache Amboss (~3h)
STATE_PATH    = "/home/admin/.cache/auto_fee_state.json"    # estado p/ circuit breaker

# Política de fee
BASE_FEE_MSAT = 0
MIN_PPM = 100
MAX_PPM = 2500
STEP_CAP = 0.20       # máx variação ±20%/rodada
COLCHAO_PPM = 50      # buffer fixo somado ao alvo

# Liquidez (ajustes)
LOW_OUTBOUND_THRESH = 0.20   # <20% outbound => sobe fee
HIGH_OUTBOUND_THRESH = 0.80  # >80% outbound => desce fee
LOW_OUTBOUND_BUMP   = 0.25   # +25%
HIGH_OUTBOUND_CUT   = 0.20   # -20%
IDLE_EXTRA_CUT      = 0.10   # -10% adicional se ocioso (0 forwards) e outbound >60%

# Ponderação por volume de ENTRADA (peers que te alimentam mais pesam mais)
VOLUME_WEIGHT_ALPHA = 0.30   # 0 desliga; 0.3 é moderado (limitado a ±30% no seed)

# Circuit breaker (recuo parcial se forwards caírem após uma alta)
CB_WINDOW_DAYS = 7
CB_DROP_RATIO  = 0.60
CB_REDUCE_STEP = 0.15
CB_GRACE_DAYS  = 10

# Lista de exclusão (opcional): deixe vazia ou popule com pubkeys a ignorar
EXCLUSION_LIST = set()       # ex.: {"033d...abc", "02ff...123"}

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

def clamp_ppm(v):
    return max(MIN_PPM, min(MAX_PPM, int(round(v))))

def fee_fraction(ppm_val):
    return ppm_val / 1_000_000.0

def apply_step_cap(current_ppm, target_ppm):
    if current_ppm <= 0:
        return clamp_ppm(target_ppm)
    delta = target_ppm - current_ppm
    cap = max(1, int(abs(current_ppm) * STEP_CAP))
    if delta > cap:
        return current_ppm + cap
    if delta < -cap:
        return current_ppm - cap
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
    data = json.loads(run(f"{LNCLI} listchannels"))
    snap = {}
    for ch in data.get("channels", []):
        cid = str(ch.get("chan_id"))
        snap[cid] = {
            "capacity": int(ch.get("capacity", 0)),
            "local_balance": int(ch.get("local_balance", 0)),
            "remote_balance": int(ch.get("remote_balance", 0)),
            "remote_pubkey": ch.get("remote_pubkey"),
            "chan_point": ch.get("channel_point"),
        }
    return snap

# ========== AMBOSS ==========
def amboss_p65_incoming_ppm(pubkey, cache):
    """
    p65 do incoming_fee_rate_metrics/weighted_corrected_mean (7d). Cache 3h.
    Retorna None se AMBOSS_TOKEN estiver vazio (desabilita seed).
    """
    if not AMBOSS_TOKEN:
        return None

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
    frac = fee_fraction(ppm_value)
    cmd = f'{BOS} fees --to {to_pubkey} --set-fee-rate {frac}'
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

    channels_meta = {}
    open_cids = set()
    for (chan_id, alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey, is_open) in meta_rows:
        cid = str(chan_id)
        channels_meta[cid] = {
            "alias": alias or "Unknown",
            "local_ppm": int(local_fee_rate or 0),
            "remote_fee_rate": int(remote_fee_rate or 0),
            "ar_max_cost": float(ar_max_cost or 0),
            "remote_pubkey": remote_pubkey,
            "is_open": int(is_open or 0),
        }
        if int(is_open or 0) == 1:
            open_cids.add(cid)

    live = listchannels_snapshot()

    # ---- Forwards (7d) para métricas de saída e in-volume por peer ----
    cur.execute(SQL_FORWARDS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    rows = cur.fetchall()

    out_fee_sat = defaultdict(int)
    out_amt_sat = defaultdict(int)
    out_count   = defaultdict(int)

    chan_pubkey = {}
    for cid, info in live.items():
        chan_pubkey[cid] = info.get("remote_pubkey")

    incoming_msat_by_pub = defaultdict(int)

    for (cid_in, cid_out, amt_in_msat, amt_out_msat, fee_sat, fwd_date) in rows:
        if cid_out:
            cid_out = str(cid_out)
            out_fee_sat[cid_out] += int(fee_sat or 0)
            out_amt_sat[cid_out] += int((amt_out_msat or 0)/1000)
            out_count[cid_out]   += 1
        if cid_in:
            cid_in = str(cid_in)
            pub = chan_pubkey.get(cid_in)
            if pub:
                incoming_msat_by_pub[pub] += int(amt_in_msat or 0)

    total_incoming_msat = sum(incoming_msat_by_pub.values())
    peer_count = max(1, len(incoming_msat_by_pub))
    avg_share = 1.0 / peer_count if peer_count > 0 else 0.0

    # ---- Custo de rebal verdadeiro (7d) via gui_payments ----
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

    zero_cap_hits = 0

    for cid in sorted(open_cids):
        meta = channels_meta.get(cid, {})
        alias = meta.get("alias", "Unknown")
        local_ppm = meta.get("local_ppm", 0)
        pubkey = (live.get(cid) or {}).get("remote_pubkey") or meta.get("remote_pubkey")
        if not pubkey:
            continue
        if pubkey in EXCLUSION_LIST:
            report.append(f"⏭️  {alias} ({cid}) skip (exclusion)")
            continue

        cap   = int((live.get(cid) or {}).get("capacity", 0))
        local = int((live.get(cid) or {}).get("local_balance", 0))
        if cap <= 0:
            zero_cap_hits += 1
        out_ratio = (local / cap) if cap > 0 else 0.5

        out_ppm_7d = ppm(out_fee_sat.get(cid, 0), out_amt_sat.get(cid, 0))
        fwd_count  = out_count.get(cid, 0)

        # Seed Amboss (p65) do peer
        p65 = amboss_p65_incoming_ppm(pubkey, cache)
        if p65 is None:
            p65 = 200.0  # fallback conservador

        # Ponderação pelo volume de ENTRADA do peer
        if total_incoming_msat > 0 and VOLUME_WEIGHT_ALPHA > 0:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            factor = 1.0 + VOLUME_WEIGHT_ALPHA * (share - avg_share)
            p65 *= max(0.7, min(1.3, factor))  # limita a ±30%

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

        # Aplica/relata
        if new_ppm != local_ppm:
            if dry_run:
                action = f"DRY set {local_ppm}→{new_ppm} ppm"
            else:
                try:
                    bos_set_fee_ppm(pubkey, new_ppm)
                    action = f"set {local_ppm}→{new_ppm} ppm"
                    new_dir = "up" if new_ppm > local_ppm else ("down" if new_ppm < local_ppm else "flat")
                    state[cid] = {
                        "last_ppm": new_ppm,
                        "last_dir": new_dir,
                        "last_ts":  now_ts,
                        # baseline pós mudança: usa fwd_count atual como semente (simples e estável)
                        "baseline_fwd7d": fwd_count if fwd_count > 0 else state_all.get("baseline_fwd7d", 0)
                    }
                except Exception as e:
                    action = f"❌ erro ao setar: {e}"
            report.append(f"✅ {alias}: {action} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{int(p65)}")
        else:
            report.append(f"🫤 {alias}: mantém {local_ppm} ppm | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)}")

    if zero_cap_hits > 0:
        report.append(f"ℹ️  {zero_cap_hits} canal(is) sem capacity no lncli listchannels (out_ratio=0.50 por fallback). Verifique LNCLI path/perm.")

    save_json(CACHE_PATH, cache)
    if not dry_run:
        save_json(STATE_PATH, state)

    msg = "\n".join(report)
    print(msg)
    if not dry_run:            # não envia quando for --dry-run
        tg_send_big(msg)       # envia quebrado em blocos de ~4000 chars

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto fee LND (Amboss seed, ponderação por entrada, liquidez e circuit-breaker)")
    parser.add_argument("--dry-run", action="store_true", help="Simula: não aplica BOS e não grava STATE")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
