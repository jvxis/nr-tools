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
MAX_PPM = 1500

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

# --- escalada por persistência de baixo outbound ---
PERSISTENT_LOW_ENABLE        = True
PERSISTENT_LOW_THRESH        = 0.10   # considera "baixo" se < 10%
PERSISTENT_LOW_BUMP          = 0.05   # +5% no alvo por rodada de streak
PERSISTENT_LOW_STREAK_MIN    = 3      # só começa a agir a partir de 3 rodadas seguidas
PERSISTENT_LOW_MAX           = 0.20   # teto de +20% acumulado
# >>> NOVAS FLAGS:
PERSISTENT_LOW_OVER_CURRENT_ENABLE = True  # se alvo <= taxa atual, escalar "over current"
PERSISTENT_LOW_MIN_STEP_PPM        = 5     # passo mínimo quando escalando "over current"

# --- peso do volume de ENTRADA do peer (Amboss) no alvo ---
VOLUME_WEIGHT_ALPHA = 0.10

# --- circuit breaker ---
CB_WINDOW_DAYS = 7
CB_DROP_RATIO  = 0.60
CB_REDUCE_STEP = 0.10
CB_GRACE_DAYS  = 10

# --- Proteção de custo de rebal (PISO) ---
REBAL_FLOOR_ENABLE = True     # habilita piso de segurança
REBAL_FLOOR_MARGIN = 0.10     # 10% acima do custo médio de rebal 7d

# --- Composição do custo no ALVO ---
#   "global"      = usa só o custo global 7d
#   "per_channel" = usa só o custo por canal 7d
#   "blend"       = mistura global e por canal
REBAL_COST_MODE = "per_channel"
REBAL_BLEND_LAMBDA = 0.30     # se "blend": 30% global, 70% canal

# --- Guard de anomalias do seed (Amboss p65) ---
SEED_GUARD_ENABLE      = True
SEED_GUARD_MAX_JUMP    = 0.50   # máx +50% vs seed anterior gravado no STATE
SEED_GUARD_P95_CAP     = True   # cap no P95 da série 7d do Amboss
SEED_GUARD_ABS_MAX_PPM = 2000   # teto absoluto opcional (0/None para desativar)

# --- Piso opcional pelo out_ppm7d (histórico de forwards) ---
OUTRATE_FLOOR_ENABLE      = True     # liga/desliga
OUTRATE_FLOOR_FACTOR      = 1     # 0.90 = não cair abaixo de 90% do out_ppm7d
OUTRATE_FLOOR_MIN_FWDS    = 5        # só vale se tiver pelo menos N forwards na janela

# =========================
# TUNING EXTRA (NOVO)
# =========================

# Step cap dinâmico
DYNAMIC_STEP_CAP_ENABLE = True
STEP_CAP_LOW_005 = 0.12   # out_ratio < 0.03
STEP_CAP_LOW_010 = 0.08   # 0.03 <= out_ratio < 0.05
STEP_CAP_IDLE_DOWN = 0.12 # fwd_count==0 & out_ratio>0.60 (queda)
STEP_MIN_STEP_PPM = 5     # passo mínimo em ppm

# Floor por canal mais robusto
REBAL_PERCHAN_MIN_VALUE_SAT = 200_000
REBAL_FLOOR_SEED_CAP_FACTOR = 1.6

# Outrate floor dinâmico
OUTRATE_FLOOR_DYNAMIC_ENABLE      = True
OUTRATE_FLOOR_DISABLE_BELOW_FWDS  = 5
OUTRATE_FLOOR_FACTOR_LOW          = 0.80

# Discovery mode
DISCOVERY_ENABLE   = True
DISCOVERY_OUT_MIN  = 0.30
DISCOVERY_FWDS_MAX = 0

# Seed smoothing (EMA leve)
SEED_EMA_ALPHA = 0.20

# ========== LUCRO/DEMANDA ==========
SURGE_ENABLE = True
SURGE_LOW_OUT_THRESH = 0.08
SURGE_K = 0.60
SURGE_BUMP_MAX = 0.35

TOP_REVENUE_SURGE_ENABLE = True
TOP_OUTFEE_SHARE = 0.20
TOP_REVENUE_SURGE_BUMP = 0.10

NEG_MARGIN_SURGE_ENABLE = True
NEG_MARGIN_SURGE_BUMP   = 0.08
NEG_MARGIN_MIN_FWDS     = 5

BOS_PUSH_MIN_ABS_PPM   = 3
BOS_PUSH_MIN_REL_FRAC  = 0.01

# ========== OFFLINE SKIP (NOVO) ==========
OFFLINE_SKIP_ENABLE = True
OFFLINE_STATUS_CACHE_KEY = "chan_status"  # onde persiste no CACHE_PATH

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

def apply_step_cap2(current_ppm, target_ppm, cap_frac=None, min_step_ppm=1):
    if current_ppm <= 0:
        return clamp_ppm(target_ppm)
    capf = float(cap_frac if cap_frac is not None else STEP_CAP)
    cap = max(int(abs(current_ppm) * capf), int(min_step_ppm))
    delta = target_ppm - current_ppm
    if delta > cap:  return current_ppm + cap
    if delta < -cap: return current_ppm - cap
    return target_ppm

def _chunk_text(text, max_len=4000):
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
            time.sleep(0.2)
        except Exception:
            pass

def has_column(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def fmt_duration(secs):
    s = int(max(0, secs))
    d = s // 86400; s %= 86400
    h = s // 3600;  s %= 3600
    m = s // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m and not d: parts.append(f"{m}m")
    return " ".join(parts) if parts else "0m"

# === utilitário p/ piso conforme REBAL_COST_MODE ===
def pick_rebal_cost_for_floor(cid, perchan_cost_map, global_cost):
    mode = (REBAL_COST_MODE or "per_channel").lower()
    lam  = max(0.0, min(1.0, float(REBAL_BLEND_LAMBDA or 0.0)))
    ch = perchan_cost_map.get(cid) or 0.0
    gl = global_cost or 0.0
    if mode == "global":
        base = gl
    elif mode == "blend":
        if ch > 0 and gl > 0:
            base = lam * gl + (1.0 - lam) * ch
        elif ch > 0:
            base = ch
        else:
            base = gl
    else:  # per_channel
        base = ch if ch > 0 else gl
    return base or 0.0

# ========== DB QUERIES ==========
SQL_FORWARDS = """
SELECT chan_id_in, chan_id_out, amt_in_msat, amt_out_msat, fee, forward_date
FROM gui_forwards
WHERE forward_date BETWEEN ? AND ?
"""
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
    Indexa snapshot do lncli de três formas + flag 'active' (online/offline).
    """
    data = json.loads(run(f"{LNCLI} listchannels"))
    by_scid_dec, by_cid_dec, by_point = {}, {}, {}
    for ch in data.get("channels", []):
        scid  = ch.get("scid")
        cid   = ch.get("chan_id")
        point = ch.get("channel_point")
        active = bool(ch.get("active", False))
        info = {
            "capacity": int(ch.get("capacity", 0)),
            "local_balance": int(ch.get("local_balance", 0)),
            "remote_balance": int(ch.get("remote_balance", 0)),
            "remote_pubkey": ch.get("remote_pubkey"),
            "chan_point": point,
            "active": active,
        }
        if scid is not None and str(scid).isdigit():
            by_scid_dec[str(scid)] = info
        if cid is not None and str(cid).isdigit():
            by_cid_dec[str(cid)] = info
        if point:
            by_point[point] = info
    return {"by_scid_dec": by_scid_dec, "by_cid_dec": by_cid_dec, "by_point": by_point}

# ========== AMBOSS ==========
def _percentile(vals, q):
    if not vals:
        return None
    vs = sorted(vals)
    if len(vs) == 1:
        return float(vs[0])
    pos = q * (len(vs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(vs[lo])
    return vs[lo] * (hi - pos) + vs[hi] * (pos - lo)

def amboss_seed_series_7d(pubkey, cache):
    key = f"incoming_series_7d:{pubkey}"
    now = int(time.time())
    if key in cache and now - cache[key]["ts"] < 3*3600:
        return cache[key]["vals"]
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
        cache[key] = {"ts": now, "vals": vals}
        return vals
    except Exception:
        return None

def seed_with_guard(pubkey, cache, state, cid):
    vals = amboss_seed_series_7d(pubkey, cache)
    if not vals:
        return 200.0, None, None, []
    raw_p65 = _percentile(vals, 0.65)
    p95     = _percentile(vals, 0.95)
    seed    = raw_p65
    flags   = []
    if SEED_GUARD_ENABLE:
        if SEED_GUARD_P95_CAP and p95 is not None and seed > p95:
            seed = p95
            flags.append("p95")
        prev_seed = (state.get(cid) or {}).get("last_seed", None)
        if prev_seed and prev_seed > 0:
            cap_prev = prev_seed * (1.0 + SEED_GUARD_MAX_JUMP)
            if seed > cap_prev:
                seed = cap_prev
                flags.append("prev+{:.0f}%".format(SEED_GUARD_MAX_JUMP*100))
        if SEED_GUARD_ABS_MAX_PPM and seed > SEED_GUARD_ABS_MAX_PPM:
            seed = float(SEED_GUARD_ABS_MAX_PPM)
            flags.append("abs")
    return float(seed), float(raw_p65), (float(p95) if p95 is not None else None), flags

# ========== BOS ==========
def bos_set_fee_ppm(to_pubkey, ppm_value):
    v = clamp_ppm(int(round(ppm_value)))
    cmd = f'{BOS} fees --to {to_pubkey} --set-fee-rate {v}'
    run(cmd)

# ========== STATE ==========
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
            cid = str(chan_id)
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
            cid = str(chan_id)
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

    # ---- Forwards (7d) ----
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
    total_out_fee_sat = sum(out_fee_sat.values())

    # ---- Custo de rebal (7d) ----
    cur.execute(SQL_REBAL_PAYMENTS, (to_sqlite_str(start_dt), to_sqlite_str(end_dt)))
    pay_rows = cur.fetchall()

    rebal_value_sat_global = 0
    rebal_fee_sat_global   = 0
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
    rebal_cost_ppm_by_chan = {
        cid: ppm(perchan_fee_sat[cid], perchan_value_sat[cid]) for cid in perchan_value_sat.keys()
    }

    rebal_cost_ppm_by_chan_use = {}
    for cid_k in set(list(perchan_value_sat.keys()) + list(rebal_cost_ppm_by_chan.keys())):
        if perchan_value_sat.get(cid_k, 0) >= REBAL_PERCHAN_MIN_VALUE_SAT:
            rebal_cost_ppm_by_chan_use[cid_k] = rebal_cost_ppm_by_chan.get(cid_k, 0)

    report = []
    report.append(f"{'DRY-RUN ' if dry_run else ''}⚙️ AutoFee | janela {LOOKBACK_DAYS}d | rebal≈ {int(rebal_cost_ppm_global)} ppm (gui_payments)")

    changed_up = changed_down = kept = 0
    low_out_count = 0
    unmatched = 0
    offline_skips = 0

    chan_status_cache = cache.get(OFFLINE_STATUS_CACHE_KEY, {})

    for cid in sorted(open_cids):
        meta = channels_meta.get(cid, {})
        alias = meta.get("alias", "Unknown")
        local_ppm = meta.get("local_ppm", 0)

        # snapshot
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

        # --- OFFLINE SKIP: detecta status e persiste em cache ---
        now_ts = int(time.time())
        active_flag = (live_info or {}).get("active", None)
        # Atualiza cache de status
        prev = chan_status_cache.get(cid, {})
        prev_active = prev.get("active", None)
        status_entry = {
            "alias": alias,
            "active": 1 if active_flag else 0 if active_flag is not None else None,
            "last_seen": now_ts,
            "last_online": prev.get("last_online"),
            "last_offline": prev.get("last_offline"),
        }
        if active_flag is True:
            status_entry["last_online"] = now_ts
        elif active_flag is False:
            status_entry["last_offline"] = status_entry.get("last_offline", now_ts)
        chan_status_cache[cid] = status_entry
        cache[OFFLINE_STATUS_CACHE_KEY] = chan_status_cache

        # monta tag de status
        status_tags = []
        if active_flag is True:
            status_tags.append("🟢on")
            if prev_active == 0:
                status_tags.append("🟢back")
        elif active_flag is False:
            status_tags.append("🔴off")

        # Se sabemos que está offline, faz skip cedo
        if OFFLINE_SKIP_ENABLE and active_flag is False:
            offline_skips += 1
            since_off = fmt_duration(now_ts - (status_entry.get("last_offline") or now_ts))
            last_on = status_entry.get("last_online")
            last_on_ago = fmt_duration(now_ts - last_on) if last_on else "n/a"
            report.append(f"⏭️🔌 {alias} ({cid}) skip: canal offline ({since_off}) | last_on≈{last_on_ago} | local {local_ppm} ppm")
            # mantém streak/seed no estado sem alterar taxa
            if not dry_run:
                st = state.get(cid, {}).copy()
                st["last_seed"] = float(st.get("last_seed", 0.0))  # no-op, só para manter chave
                state[cid] = st
            continue

        # prossegue normal (online ou status desconhecido)
        cap   = int((live_info or {}).get("capacity", 0))
        local = int((live_info or {}).get("local_balance", 0))
        out_ratio = (local / cap) if cap > 0 else 0.5
        if out_ratio < PERSISTENT_LOW_THRESH:
            low_out_count += 1

        out_ppm_7d = ppm(out_fee_sat.get(cid, 0), out_amt_sat.get(cid, 0))
        fwd_count  = out_count.get(cid, 0)

        # Seed (Amboss) com guard
        seed_used, seed_raw, seed_p95, seed_flags = seed_with_guard(pubkey, cache, state, cid)
        if seed_used is None:
            seed_used = 200.0

        # Ponderação pelo volume de ENTRADA do peer
        if total_incoming_msat > 0 and VOLUME_WEIGHT_ALPHA > 0 and pubkey:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            factor = 1.0 + VOLUME_WEIGHT_ALPHA * (share - avg_share)
            seed_used *= max(0.7, min(1.3, factor))

        # EMA leve no seed
        prev_seed_for_ema = (state.get(cid, {}) or {}).get("last_seed")
        if SEED_EMA_ALPHA and SEED_EMA_ALPHA > 0 and prev_seed_for_ema and prev_seed_for_ema > 0:
            seed_used = float(prev_seed_for_ema)*(1.0 - SEED_EMA_ALPHA) + float(seed_used)*SEED_EMA_ALPHA

        # tags do guard do seed
        seed_tags = []
        for fl in (seed_flags or []):
            if fl == "p95": seed_tags.append("🧬seedcap:p95")
            elif fl.startswith("prev+"): seed_tags.append("🧬seedcap:" + fl)
            elif fl == "abs": seed_tags.append("🧬seedcap:abs")

        # persistir last_seed cedo
        if not dry_run:
            st_tmp = state.get(cid, {}).copy()
            st_tmp["last_seed"] = float(seed_used)
            state[cid] = st_tmp

        # --- Alvo BASE ---
        target_base = seed_used + COLCHAO_PPM
        target = target_base

        # --- Escalada por persistência de baixo outbound ---
        streak = state.get(cid, {}).get("low_streak", 0)
        if PERSISTENT_LOW_ENABLE:
            if out_ratio < PERSISTENT_LOW_THRESH:
                streak += 1
            else:
                streak = 0
            if streak >= PERSISTENT_LOW_STREAK_MIN:
                bump_acc = (streak - PERSISTENT_LOW_STREAK_MIN + 1) * PERSISTENT_LOW_BUMP
                bump_acc = min(PERSISTENT_LOW_MAX, max(0.0, bump_acc))
                bump_mult = 1.0 + bump_acc
                if PERSISTENT_LOW_OVER_CURRENT_ENABLE and target <= local_ppm:
                    target = max(target, int(math.ceil(local_ppm * bump_mult)), local_ppm + int(PERSISTENT_LOW_MIN_STEP_PPM or 0))
                    bump_mode = "over_current"
                else:
                    target = int(math.ceil(target * bump_mult))
                    bump_mode = "seed"
                report.append(f"📈 Persistência: {alias} ({cid}) streak {streak} ⇒ bump {bump_acc*100:.0f}% ({bump_mode})")

        # --- Liquidez ---
        if out_ratio < LOW_OUTBOUND_THRESH:
            target *= (1.0 + LOW_OUTBOUND_BUMP)
        elif out_ratio > HIGH_OUTBOUND_THRESH:
            target *= (1.0 - HIGH_OUTBOUND_CUT)
            if fwd_count == 0 and out_ratio > 0.60:
                target *= (1.0 - IDLE_EXTRA_CUT)

        # --- Surge pricing ---
        surge_tag = ""
        if SURGE_ENABLE and out_ratio < SURGE_LOW_OUT_THRESH:
            lack = max(0.0, (SURGE_LOW_OUT_THRESH - out_ratio) / SURGE_LOW_OUT_THRESH)
            surge_bump = min(SURGE_BUMP_MAX, SURGE_K * lack)
            if surge_bump > 0:
                target = int(math.ceil(target * (1.0 + surge_bump)))
                surge_tag = f"⚡surge+{int(surge_bump*100)}%"

        target = clamp_ppm(target)

        # Guard low: não reduzir quando drenado
        pl_tags = []
        if out_ratio < PERSISTENT_LOW_THRESH and target < local_ppm:
            target = local_ppm
            pl_tags.append("🙅‍♂️no-down-low")

        # Step cap dinâmico
        cap_frac = STEP_CAP
        if DYNAMIC_STEP_CAP_ENABLE:
            if out_ratio < 0.03:
                cap_frac = max(cap_frac, STEP_CAP_LOW_005)
            elif out_ratio < 0.05:
                cap_frac = max(cap_frac, STEP_CAP_LOW_010)
            if fwd_count == 0 and out_ratio > 0.60:
                cap_frac = max(cap_frac, STEP_CAP_IDLE_DOWN)

        # Discovery
        discovery_hit = False
        if DISCOVERY_ENABLE and fwd_count <= DISCOVERY_FWDS_MAX and out_ratio > DISCOVERY_OUT_MIN:
            discovery_hit = True
            cap_frac = max(cap_frac, STEP_CAP_IDLE_DOWN)

        raw_step_ppm = target if local_ppm == 0 else apply_step_cap2(local_ppm, target, cap_frac, STEP_MIN_STEP_PPM)

        # Circuit breaker
        now_ts = int(time.time())
        state_all = state.get(cid, {})
        last_ppm  = state_all.get("last_ppm", local_ppm)
        last_dir  = state_all.get("last_dir", "flat")
        last_ts   = state_all.get("last_ts", 0)
        baseline  = state_all.get("baseline_fwd7d", None)
        if last_dir == "up" and (now_ts - last_ts) <= CB_GRACE_DAYS*24*3600 and baseline:
            if baseline > 0 and fwd_count < baseline * CB_DROP_RATIO:
                raw_step_ppm = clamp_ppm(int(raw_step_ppm * (1.0 - CB_REDUCE_STEP)))
                report.append(f"🧯 CB: {alias} ({cid}) fwd {fwd_count}<{int(baseline*CB_DROP_RATIO)} ⇒ recuo {int(CB_REDUCE_STEP*100)}%")

        # Piso rebal
        if REBAL_FLOOR_ENABLE:
            base_cost = pick_rebal_cost_for_floor(cid, rebal_cost_ppm_by_chan_use, rebal_cost_ppm_global)
            if base_cost > 0:
                floor_ppm = clamp_ppm(math.ceil(base_cost * (1.0 + REBAL_FLOOR_MARGIN)))
            else:
                floor_ppm = MIN_PPM
        else:
            floor_ppm = MIN_PPM

        # Outrate floor dinâmico
        outrate_floor_active = OUTRATE_FLOOR_ENABLE
        outrate_factor = OUTRATE_FLOOR_FACTOR
        if OUTRATE_FLOOR_DYNAMIC_ENABLE:
            if fwd_count < OUTRATE_FLOOR_DISABLE_BELOW_FWDS:
                outrate_floor_active = False
            elif fwd_count < 10:
                outrate_factor = OUTRATE_FLOOR_FACTOR_LOW
        if discovery_hit:
            outrate_floor_active = False
        out_ppm_7d = ppm(out_fee_sat.get(cid, 0), out_amt_sat.get(cid, 0))
        if outrate_floor_active and fwd_count >= OUTRATE_FLOOR_MIN_FWDS and out_ppm_7d > 0:
            outrate_floor = clamp_ppm(math.ceil(out_ppm_7d * outrate_factor))
            floor_ppm = max(floor_ppm, outrate_floor)

        # Cap do floor pelo seed
        floor_ppm = min(floor_ppm, clamp_ppm(int(math.ceil(seed_used * REBAL_FLOOR_SEED_CAP_FACTOR))))

        # Métricas lucro
        base_cost_for_margin = pick_rebal_cost_for_floor(cid, rebal_cost_ppm_by_chan_use, rebal_cost_ppm_global)
        margin_ppm_7d = int(round(out_ppm_7d - (base_cost_for_margin * (1.0 + REBAL_FLOOR_MARGIN)))) if base_cost_for_margin else int(round(out_ppm_7d))
        rev_share = (out_fee_sat.get(cid, 0) / total_out_fee_sat) if total_out_fee_sat > 0 else 0.0

        # Top revenue surge
        if TOP_REVENUE_SURGE_ENABLE and rev_share >= TOP_OUTFEE_SHARE and out_ratio < 0.30:
            target_boost = int(math.ceil(target * TOP_REVENUE_SURGE_BUMP))
            raw_step_ppm = clamp_ppm(max(raw_step_ppm, target + target_boost))
            surge_tag = (surge_tag + " " if surge_tag else "") + f"👑top+{int(TOP_REVENUE_SURGE_BUMP*100)}%"

        # Margem negativa
        if NEG_MARGIN_SURGE_ENABLE and margin_ppm_7d < 0 and fwd_count >= NEG_MARGIN_MIN_FWDS:
            bump = int(math.ceil(target * NEG_MARGIN_SURGE_BUMP))
            raw_step_ppm = clamp_ppm(max(raw_step_ppm, target + bump))
            surge_tag = (surge_tag + " " if surge_tag else "") + f"💹negm+{int(NEG_MARGIN_SURGE_BUMP*100)}%"

        final_ppm = max(raw_step_ppm, floor_ppm)

        # Diagnóstico
        diag_tags = []
        if raw_step_ppm != target:
            dir_same = (target > local_ppm and raw_step_ppm > local_ppm) or (target < local_ppm and raw_step_ppm < local_ppm)
            if dir_same:
                diag_tags.append("⛔stepcap")
        if final_ppm < target and final_ppm == floor_ppm:
            diag_tags.append("🧱floor-lock")
        if final_ppm == local_ppm and target != local_ppm and floor_ppm <= local_ppm:
            diag_tags.append("⛔stepcap-lock")
        if discovery_hit:
            diag_tags.append("🧪discovery")
        if surge_tag:
            diag_tags.append(surge_tag)
        diag_tags += status_tags  # adiciona status 🟢on/🟢back

        all_tags = pl_tags + seed_tags + diag_tags
        new_ppm = final_ppm

        # Aplica/relata
        seed_note = f"{int(seed_used)}" + (" (cap)" if seed_flags else "")
        dir_for_emoji = "up" if new_ppm > local_ppm else ("down" if new_ppm < local_ppm else "flat")
        emo = "🔺" if dir_for_emoji == "up" else ("🔻" if dir_for_emoji == "down" else "⏸️")

        push_forced_by_floor = (floor_ppm > local_ppm and new_ppm > local_ppm)
        will_push = True
        if new_ppm != local_ppm and not push_forced_by_floor:
            delta_ppm = abs(new_ppm - local_ppm)
            rel = delta_ppm / max(1, local_ppm)
            if delta_ppm < BOS_PUSH_MIN_ABS_PPM and rel < BOS_PUSH_MIN_REL_FRAC:
                will_push = False

        if new_ppm != local_ppm and will_push:
            delta = new_ppm - local_ppm
            pct = (abs(delta) / local_ppm * 100.0) if local_ppm > 0 else 0.0
            dstr = f"{'+' if delta>0 else ''}{delta} ({pct:.1f}%)"
            if dry_run:
                action = f"DRY set {local_ppm}→{new_ppm} ppm {dstr}"
                new_dir = dir_for_emoji
            else:
                try:
                    if pubkey:
                        bos_set_fee_ppm(pubkey, new_ppm)
                        action = f"set {local_ppm}→{new_ppm} ppm {dstr}"
                        new_dir = dir_for_emoji
                        st = state.get(cid, {}).copy()
                        old_base = st.get("baseline_fwd7d", 0)
                        if fwd_count > 0:
                            if old_base and old_base > 0:
                                new_base = int(round(0.7*old_base + 0.3*fwd_count))
                            else:
                                new_base = fwd_count
                        else:
                            new_base = old_base
                        st.update({
                            "last_ppm": new_ppm,
                            "last_dir": new_dir,
                            "last_ts":  int(time.time()),
                            "baseline_fwd7d": new_base,
                            "low_streak": streak if PERSISTENT_LOW_ENABLE else 0,
                            "last_seed": float(seed_used),
                        })
                        state[cid] = st
                    else:
                        action = "❌ sem pubkey/snapshot p/ aplicar"
                        new_dir = "flat"
                except Exception as e:
                    action = f"❌ erro ao setar: {e}"
                    new_dir = "flat"

            report.append(
                f"✅{emo} {alias}: {action} | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{seed_note} | floor≥{floor_ppm} | marg≈{margin_ppm_7d} | rev_share≈{rev_share:.2f} | {' '.join(all_tags)}"
            )
            if new_ppm > local_ppm: changed_up += 1
            else: changed_down += 1

        else:
            if not dry_run:
                st = state.get(cid, {}).copy()
                st["low_streak"] = streak if PERSISTENT_LOW_ENABLE else 0
                st["last_seed"] = float(seed_used)
                state[cid] = st
            kept += 1
            hold_tag = "" if will_push else " 🧘hold-small"
            report.append(
                f"🫤⏸️ {alias}: mantém {local_ppm} ppm{hold_tag} | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{seed_note} | floor≥{floor_ppm} | marg≈{margin_ppm_7d} | rev_share≈{rev_share:.2f} | {' '.join(all_tags)}"
            )

    # resumo na 2ª linha do relatório
    report.insert(1, f"📊 up {changed_up} | down {changed_down} | flat {kept} | low_out {low_out_count} | offline {offline_skips}")

    if unmatched > 0:
        report.append(f"ℹ️  {unmatched} canal(is) sem snapshot por scid/chan_point (out_ratio=0.50 por fallback). Cheque versão do lncli e permissões.")

    save_json(CACHE_PATH, cache)
    if not dry_run:
        save_json(STATE_PATH, state)

    msg = "\n".join(report)
    print(msg)
    if not dry_run:
        tg_send_big(msg)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto fee LND (Amboss seed com guard, EMA, ponderação por entrada, liquidez, surge, piso robusto, persistência over-current, discovery, circuit-breaker, gate anti-microupdate e skip offline)")
    parser.add_argument("--dry-run", action="store_true", help="Simula: não aplica BOS e não grava STATE")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

