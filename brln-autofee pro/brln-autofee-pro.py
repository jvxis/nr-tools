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

# =========================
# CONFIG (perfil conservador pró-lucro)
# =========================

LOOKBACK_DAYS = 7
CACHE_PATH    = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH    = "/home/admin/.cache/auto_fee_state.json"

# --- limites base ---
BASE_FEE_MSAT = 0
MIN_PPM = 100          # protege receita mínima
MAX_PPM = 1500         # teto padrão
# MOD: clamp final explícito será aplicado no final do cálculo (higiene)

# --- “velocidade” de mudança por execução (padrão) ---
STEP_CAP = 0.05        # muda no máx. 5% por rodada

# --- colchão fixo no alvo ---
COLCHAO_PPM = 25

# --- política de variação por liquidez (faixa morta: 5%–30%) ---
LOW_OUTBOUND_THRESH = 0.05   # <5% outbound = drenado ⇒ leve alta
HIGH_OUTBOUND_THRESH = 0.20  # >20% outbound = sobrando ⇒ leve queda
LOW_OUTBOUND_BUMP   = 0.01   # +1% no alvo quando <5%
HIGH_OUTBOUND_CUT   = 0.01   # -1% no alvo quando >20%
IDLE_EXTRA_CUT      = 0.005  # corte quase nulo por ociosidade

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
VOLUME_WEIGHT_ALPHA = 0.20  # MOD: 0.10 → 0.20 (ponderação de entrada mais forte)

# --- circuit breaker ---
CB_WINDOW_DAYS = 7
CB_DROP_RATIO  = 0.70   # reage mais cedo se fluxo cair
CB_REDUCE_STEP = 0.10
CB_GRACE_DAYS  = 7      # janela de observação menor

# --- Proteção de custo de rebal (PISO) ---
REBAL_FLOOR_ENABLE = True      # habilita piso de segurança
REBAL_FLOOR_MARGIN = 0.10      # 10% acima do custo médio de rebal 7d

# --- Composição do custo no ALVO ---
#   "global"      = usa só o custo global 7d
#   "per_channel" = usa só o custo por canal 7d
#   "blend"       = mistura global e por canal
REBAL_COST_MODE = "per_channel"
REBAL_BLEND_LAMBDA = 0.30      # se "blend": 30% global, 70% canal

# --- Guard de anomalias do seed (Amboss p65) ---
SEED_GUARD_ENABLE      = True
SEED_GUARD_MAX_JUMP    = 0.50   # máx +50% vs seed anterior gravado no STATE
SEED_GUARD_P95_CAP     = True   # cap no P95 da série 7d do Amboss
SEED_GUARD_ABS_MAX_PPM = 1600   # teto absoluto opcional (0/None para desativar)

# --- Piso opcional pelo out_ppm7d (histórico de forwards) ---
OUTRATE_FLOOR_ENABLE      = True
OUTRATE_FLOOR_FACTOR      = 1
OUTRATE_FLOOR_MIN_FWDS    = 5

# =========================
# TUNING EXTRA
# =========================

# Step cap dinâmico
DYNAMIC_STEP_CAP_ENABLE = True
STEP_CAP_LOW_005 = 0.10   # out_ratio < 0.03
STEP_CAP_LOW_010 = 0.07   # 0.03 <= out_ratio < 0.05
STEP_CAP_IDLE_DOWN = 0.10 # fwd_count==0 & out_ratio>0.60 (queda)
STEP_MIN_STEP_PPM = 5     # passo mínimo em ppm

# Floor por canal mais robusto
REBAL_PERCHAN_MIN_VALUE_SAT = 400_000  # 200k -> 400k: precisa sinal real para usar custo por canal
REBAL_FLOOR_SEED_CAP_FACTOR = 1.4      # teto do floor relativo ao seed

# Outrate floor dinâmico
OUTRATE_FLOOR_DYNAMIC_ENABLE      = True
OUTRATE_FLOOR_DISABLE_BELOW_FWDS  = 5     # liga mais cedo
OUTRATE_FLOOR_FACTOR_LOW          = 0.90  # piso um pouco maior

# Discovery mode: sem forwards e liquidez sobrando -> queda mais rápida e sem outrate floor
DISCOVERY_ENABLE   = True
DISCOVERY_OUT_MIN  = 0.30  # >30% outbound = sobra
DISCOVERY_FWDS_MAX = 0
# MOD: hard-drop extra para canais realmente ociosos
DISCOVERY_HARDDROP_DAYS_NO_BASE = 10   # se nunca gerou baseline em 10d, acelerar quedas
DISCOVERY_HARDDROP_CAP_FRAC     = 0.20 # step cap para QUEDAS
DISCOVERY_HARDDROP_COLCHAO      = 10   # colchão efetivo reduzido

# Seed smoothing (EMA leve)
SEED_EMA_ALPHA = 0.20  # 0 desliga

# ========== LUCRO/DEMANDA ==========
# 1) Surge pricing quando muito drenado
SURGE_ENABLE = True
SURGE_LOW_OUT_THRESH = 0.10
SURGE_K = 0.50
SURGE_BUMP_MAX = 0.20

# 2) Bump em peers TOP de receita
TOP_REVENUE_SURGE_ENABLE = True
TOP_OUTFEE_SHARE = 0.20
TOP_REVENUE_SURGE_BUMP = 0.12

# MOD: Extreme drain mode (acelera SUBIDAS quando drenado crônico com demanda)
EXTREME_DRAIN_ENABLE       = True
EXTREME_DRAIN_STREAK       = 20     # ativa se low_streak ≥ 20
EXTREME_DRAIN_OUT_MAX      = 0.03   # e out_ratio < 3%
EXTREME_DRAIN_STEP_CAP     = 0.15   # step cap p/ SUBIR
EXTREME_DRAIN_MIN_STEP_PPM = 15     # passo mínimo p/ SUBIR

# MOD: Revenue floor (piso por tráfego) p/ super-rotas muito ativas
REVFLOOR_ENABLE            = True
REVFLOOR_BASELINE_THRESH   = 150
REVFLOOR_MIN_PPM_ABS       = 140

# 3) Margem 7d negativa
NEG_MARGIN_SURGE_ENABLE = True
NEG_MARGIN_SURGE_BUMP   = 0.05
NEG_MARGIN_MIN_FWDS     = 5

# 4) Evitar “micro-updates” no BOS (MAIS DURO p/ 1h)
BOS_PUSH_MIN_ABS_PPM   = 15     # ↑
BOS_PUSH_MIN_REL_FRAC  = 0.04   # ↑

# ========== OFFLINE SKIP ==========
OFFLINE_SKIP_ENABLE = True
OFFLINE_STATUS_CACHE_KEY = "chan_status"

# ========== SURGE RESPEITA STEPCAP ==========
SURGE_RESPECT_STEPCAP = True

# ========== HISTERÉSE (COOLDOWN) ==========
APPLY_COOLDOWN_ENABLE = True
COOLDOWN_HOURS_UP   = 3
COOLDOWN_HOURS_DOWN = 6
COOLDOWN_FWDS_MIN   = 2
COOLDOWN_PROFIT_DOWN_ENABLE = True
COOLDOWN_PROFIT_MARGIN_MIN  = 0
COOLDOWN_PROFIT_FWDS_MIN    = 10

# ========== SHARDING ==========
SHARDING_ENABLE = False
SHARD_MOD = 3

# ========== NEW INBOUND NORMALIZE ==========
NEW_INBOUND_NORMALIZE_ENABLE   = True
NEW_INBOUND_GRACE_HOURS        = 48
NEW_INBOUND_OUT_MAX            = 0.05
NEW_INBOUND_REQUIRE_NO_FWDS    = True
NEW_INBOUND_MIN_DIFF_FRAC      = 0.25
NEW_INBOUND_MIN_DIFF_PPM       = 50
NEW_INBOUND_DOWN_STEPCAP_FRAC  = 0.15
NEW_INBOUND_TAG                = "🌱new-inbound"

# ========== DEBUG ==========
DEBUG_TAGS = True

# ========== EXCL-Dry VERBOSE / TAG-ONLY ==========
EXCL_DRY_VERBOSE = True

# ========== CLASSIFICAÇÃO DINÂMICA (sink/source/router) ==========
CLASSIFY_ENABLE                = True
CLASS_BIAS_EMA_ALPHA           = 0.45

# >>> AJUSTES
CLASS_MIN_FWDS                 = 4
CLASS_MIN_VALUE_SAT            = 40_000
SINK_BIAS_MIN                  = 0.50
SINK_OUTRATIO_MAX              = 0.15
SOURCE_BIAS_MIN                = 0.35
SOURCE_OUTRATIO_MIN            = 0.58
ROUTER_BIAS_MAX                = 0.30
CLASS_CONF_HYSTERESIS          = 0.10

# Políticas por classe
SINK_EXTRA_FLOOR_MARGIN        = 0.05
SINK_MIN_OVER_SEED_FRAC        = 0.90
SOURCE_SEED_TARGET_FRAC        = 0.60
SOURCE_DISABLE_OUTRATE_FLOOR   = True
ROUTER_STEP_CAP_BONUS          = 0.02

# Etiquetas
TAG_SINK     = "🏷️sink"
TAG_SOURCE   = "🏷️source"
TAG_ROUTER   = "🏷️router"
TAG_UNKNOWN  = "🏷️unknown"

# Persistir classe em dry-run?
DRYRUN_SAVE_CLASS = True

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
    """cap estático (compat)"""
    if current_ppm <= 0:
        return clamp_ppm(target_ppm)
    delta = target_ppm - current_ppm
    cap = max(1, int(abs(current_ppm) * STEP_CAP))
    if delta > cap:  return current_ppm + cap
    if delta < -cap: return current_ppm - cap
    return target_ppm

# === step cap dinâmico (novo) ===
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

# === utilitário p/ piso conforme REBAL_COST_MODE ===
def pick_rebal_cost_for_floor(cid, perchan_cost_map, global_cost):
    """
    Retorna o custo-base em ppm para formar o piso, conforme REBAL_COST_MODE.
    - per_channel: usa custo do canal se houver; senão, global.
    - global: sempre o custo global.
    - blend: mistura lambda*global + (1-lambda)*canal; com fallbacks.
    """
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
    else:  # per_channel (padrão)
        base = ch if ch > 0 else gl

    return base or 0.0

# ========== DB QUERIES ==========
SQL_FORWARDS = """
SELECT chan_id_in, chan_id_out, amt_in_msat, amt_out_msat, fee, forward_date
FROM gui_forwards
WHERE forward_date BETWEEN ? AND ?
"""
# inclui rebal_chan para piso por canal
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
    Indexa o snapshot do lncli de três formas + flags 'active' e 'initiator'.
    """
    data = json.loads(run(f"{LNCLI} listchannels"))
    by_scid_dec = {}
    by_cid_dec  = {}
    by_point    = {}
    for ch in data.get("channels", []):
        scid = ch.get("scid")        # decimal em string
        cid  = ch.get("chan_id")     # decimal em string (em versões novas do LND)
        point = ch.get("channel_point")
        active = bool(ch.get("active", False))
        initiator = ch.get("initiator")
        if initiator is None:
            initiator = ch.get("initiated")  # fallback raro

        info = {
            "capacity": int(ch.get("capacity", 0)),
            "local_balance": int(ch.get("local_balance", 0)),
            "remote_balance": int(ch.get("remote_balance", 0)),
            "remote_pubkey": ch.get("remote_pubkey"),
            "chan_point": point,
            "active": active,
            "initiator": bool(initiator) if initiator is not None else None,
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
    """Percentil linear (0..1)."""
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
    """Busca série 7d de incoming_fee_rate_metrics/weighted_corrected_mean. Cache 3h."""
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
    """
    Retorna (seed_usado, raw_p65, p95, flags)
    Aplica guardas: p95-cap, jump vs seed anterior e teto absoluto.
    """
    vals = amboss_seed_series_7d(pubkey, cache)
    if not vals:
        return 200.0, None, None, []  # fallback conservador

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
    # envia SEMPRE inteiro em PPM pro bos
    v = clamp_ppm(int(round(ppm_value)))
    cmd = f'{BOS} fees --to {to_pubkey} --set-fee-rate {v}'
    run(cmd)

# ========== STATE ==========
def get_state():
    return load_json(STATE_PATH, {})

def update_state(state, dry_run):
    if not dry_run:
        save_json(STATE_PATH, state)

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

# ========== PIPELINE ==========
def main(dry_run=False):
    global EXCL_DRY_VERBOSE

    # Override por variável de ambiente (sem quebrar compat)
    env_excl = os.getenv("EXCL_DRY_VERBOSE")
    if env_excl is not None:
        EXCL_DRY_VERBOSE = str(env_excl).strip().lower() in ("1","true","yes","on")

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
            cid = str(chan_id)  # SCID DECIMAL
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

    # ENTRADA p/ classificar sources/routers
    in_amt_sat_by_cid  = defaultdict(int)
    in_count_by_cid    = defaultdict(int)

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
            in_amt_sat_by_cid[k] += int((amt_in_msat or 0)/1000)
            in_count_by_cid[k]   += 1
            pub = chan_pubkey.get(k)
            if pub:
                incoming_msat_by_pub[pub] += int(amt_in_msat or 0)

    total_incoming_msat = sum(incoming_msat_by_pub.values())
    peer_count = max(1, len(incoming_msat_by_pub))
    avg_share = 1.0 / peer_count if peer_count > 0 else 0.0

    # Receita total de fees de saída
    total_out_fee_sat = sum(out_fee_sat.values())

    # ---- Custo de rebal (7d) GLOBAL e POR CANAL ----
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

    # --- Robustez: só usa custo por canal se teve volume mínimo ---
    rebal_cost_ppm_by_chan_use = {}
    for cid_k in set(list(perchan_value_sat.keys()) + list(rebal_cost_ppm_by_chan.keys())):
        if perchan_value_sat.get(cid_k, 0) >= REBAL_PERCHAN_MIN_VALUE_SAT:
            rebal_cost_ppm_by_chan_use[cid_k] = rebal_cost_ppm_by_chan.get(cid_k, 0)

    # ==== SHARDING SLOT ====
    now_ts = int(time.time())
    shard_slot = None
    if SHARDING_ENABLE:
        shard_slot = (now_ts // 3600) % SHARD_MOD

    report = []
    hdr = f"{'DRY-RUN ' if dry_run else ''}⚙️ AutoFee | janela {LOOKBACK_DAYS}d | rebal≈ {int(rebal_cost_ppm_global)} ppm (gui_payments)"
    if SHARDING_ENABLE:
        hdr += f" | shard {shard_slot+1}/{SHARD_MOD}"
    report.append(hdr)

    # --- métricas p/ resumo ---
    changed_up = changed_down = kept = 0
    low_out_count = 0
    unmatched = 0
    offline_skips = 0
    shard_skips = 0
    excl_dry_up = excl_dry_down = excl_dry_kept = 0
    max_hits = 0  # << telemetria: canais que ficaram no MAX_PPM

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

        # ==== EXCLUSION: vira DRY-RUN especial ====
        is_excluded = (pubkey in EXCLUSION_LIST) if pubkey else False

        # ---- SHARDING: pular canais não pertencentes ao slot atual ----
        if SHARDING_ENABLE:
            try:
                cid_int = int(cid)
            except Exception:
                digits = ''.join([c for c in cid if c.isdigit()])
                cid_int = int(digits[-6:] or "0")
            if (cid_int % SHARD_MOD) != shard_slot:
                shard_skips += 1
                report.append(f"⏭️🧩 {alias} ({cid}) skip (shard {shard_slot+1}/{SHARD_MOD})")
                continue

        # --- OFFLINE SKIP: detecta status e persiste em cache ---
        now_ts = int(time.time())
        active_flag = (live_info or {}).get("active", None)
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
            if is_excluded and not EXCL_DRY_VERBOSE:
                report.append(f"⏭️🔌 {alias}: 🚷excl-dry")
                continue

            since_off = fmt_duration(now_ts - (status_entry.get("last_offline") or now_ts))
            last_on = status_entry.get("last_online")
            last_on_ago = fmt_duration(now_ts - last_on) if last_on else "n/a"
            extra = " 🚷excl-dry" if is_excluded else ""
            report.append(f"⏭️🔌 {alias} ({cid}) skip: canal offline ({since_off}) | last_on≈{last_on_ago} | local {local_ppm} ppm{extra}")
            if (not dry_run) and (not is_excluded):
                st = state.get(cid, {}).copy()
                st["last_seed"] = float(st.get("last_seed", 0.0))
                state[cid] = st
            continue

        # prossegue normal (online ou status desconhecido)
        cap   = int((live_info or {}).get("capacity", 0))
        local = int((live_info or {}).get("local_balance", 0))
        remote= int((live_info or {}).get("remote_balance", 0))
        out_ratio = (local / cap) if cap > 0 else 0.5
        if out_ratio < PERSISTENT_LOW_THRESH:
            low_out_count += 1

        # detecção de initiator (se o peer abriu, initiator=False)
        initiator = (live_info or {}).get("initiator", None)

        out_ppm_7d = ppm(out_fee_sat.get(cid, 0), out_amt_sat.get(cid, 0))
        fwd_count  = out_count.get(cid, 0)

        # in/out por canal p/ classificação
        in_amt      = in_amt_sat_by_cid.get(cid, 0)
        in_count    = in_count_by_cid.get(cid, 0)
        out_amt     = out_amt_sat.get(cid, 0)
        out_cnt     = out_count.get(cid, 0)
        total_val   = in_amt + out_amt
        total_fwds  = in_count + out_cnt

        # Seed (Amboss) com guard
        seed_used, seed_raw, seed_p95, seed_flags = seed_with_guard(pubkey, cache, state, cid)
        if seed_used is None:
            seed_used = 200.0  # fallback

        # Ponderação pelo volume de ENTRADA do peer
        if total_incoming_msat > 0 and VOLUME_WEIGHT_ALPHA > 0 and pubkey:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            factor = 1.0 + VOLUME_WEIGHT_ALPHA * (share - avg_share)
            seed_used *= max(0.7, min(1.3, factor))

        # EMA leve no seed (suaviza saltos)
        prev_seed_for_ema = (state.get(cid, {}) or {}).get("last_seed")
        if SEED_EMA_ALPHA and SEED_EMA_ALPHA > 0 and prev_seed_for_ema and prev_seed_for_ema > 0:
            seed_used = float(prev_seed_for_ema)*(1.0 - SEED_EMA_ALPHA) + float(seed_used)*SEED_EMA_ALPHA

        # tags do guard do seed
        seed_tags = []
        for fl in (seed_flags or []):
            if fl == "p95": seed_tags.append("🧬seedcap:p95")
            elif fl.startswith("prev+"): seed_tags.append("🧬seedcap:" + fl)
            elif fl == "abs": seed_tags.append("🧬seedcap:abs")
        if not seed_flags and DEBUG_TAGS:
            seed_tags.append("🧬seedcap:none")

        # persistir last_seed cedo (só se não for excl-dry e não for --dry-run)
        if (not dry_run) and (not is_excluded):
            st_tmp = state.get(cid, {}).copy()
            st_tmp.setdefault("first_seen_ts", int(time.time()))
            st_tmp["last_seed"] = float(seed_used)
            state[cid] = st_tmp

        # --- Métricas de lucro p/ boosts ---
        base_cost_for_margin = pick_rebal_cost_for_floor(cid, rebal_cost_ppm_by_chan_use, rebal_cost_ppm_global)
        margin_ppm_7d = int(round(out_ppm_7d - (base_cost_for_margin * (1.0 + REBAL_FLOOR_MARGIN)))) if base_cost_for_margin else int(round(out_ppm_7d))
        rev_share = (out_fee_sat.get(cid, 0) / total_out_fee_sat) if total_out_fee_sat > 0 else 0.0

        # --- Alvo BASE: seed + colchão ---
        target_base = seed_used + COLCHAO_PPM
        target = target_base

        # ==== NEW INBOUND NORMALIZE (detecção) ====
        st_prev = state.get(cid, {}) or {}
        first_seen_ts = st_prev.get("first_seen_ts", int(time.time()))
        hours_since_first = (int(time.time()) - first_seen_ts) / 3600 if first_seen_ts else 999

        need_big_drop_vs_seed = (local_ppm >= max(seed_used*(1.0+NEW_INBOUND_MIN_DIFF_FRAC), seed_used + NEW_INBOUND_MIN_DIFF_PPM))
        peer_opened = (initiator is False)  # se info disponível
        new_inbound = (
            NEW_INBOUND_NORMALIZE_ENABLE and
            hours_since_first <= NEW_INBOUND_GRACE_HOURS and
            out_ratio <= NEW_INBOUND_OUT_MAX and
            (not fwd_count if NEW_INBOUND_REQUIRE_NO_FWDS else True) and
            need_big_drop_vs_seed and
            (peer_opened if initiator is not None else True)
        )

        # --- Classificação dinâmica sink/source/router ---
        class_label = st_prev.get("class_label", "unknown")
        class_conf  = float(st_prev.get("class_conf", 0.0))
        bias_prev   = float(st_prev.get("bias_ema", 0.0))

        bias_raw = 0.0
        if total_val > 0:
            bias_raw = (out_amt - in_amt) / float(total_val)  # [-1..1], >0 tende a sink, <0 tende a source
        bias_ema = (1.0 - CLASS_BIAS_EMA_ALPHA) * bias_prev + CLASS_BIAS_EMA_ALPHA * bias_raw if CLASSIFY_ENABLE else bias_raw

        # Decisão somente com amostra mínima e volume relevante
        cand_label = "unknown"
        cand_conf  = 0.0

        if CLASSIFY_ENABLE and total_fwds >= CLASS_MIN_FWDS and total_val >= CLASS_MIN_VALUE_SAT:
            if (bias_ema >= SINK_BIAS_MIN) and (out_ratio < SINK_OUTRATIO_MAX):
                cand_label = "sink"
                cand_conf  = min(1.0, (bias_ema - SINK_BIAS_MIN) / (1.0 - SINK_BIAS_MIN) + 0.3)
            elif (bias_ema <= -SOURCE_BIAS_MIN) and (out_ratio > SOURCE_OUTRATIO_MIN):
                cand_label = "source"
                cand_conf  = min(1.0, ((-bias_ema) - SOURCE_BIAS_MIN) / (1.0 - SOURCE_BIAS_MIN) + 0.3)
            elif abs(bias_ema) <= ROUTER_BIAS_MAX and in_count > 0 and out_cnt > 0:
                cand_label = "router"
                cand_conf  = min(1.0, (ROUTER_BIAS_MAX - abs(bias_ema)) / ROUTER_BIAS_MAX + 0.3)

        # boosts conservadores pró-source
        no_rebal_to_this_chan = (perchan_value_sat.get(cid, 0) == 0)
        if cand_label in ("unknown", "source") and no_rebal_to_this_chan and bias_ema <= -(SOURCE_BIAS_MIN - 0.05):
            cand_label = "source"
            cand_conf  = min(1.0, cand_conf + 0.20)

        if pubkey and total_incoming_msat > 0:
            share = incoming_msat_by_pub.get(pubkey, 0) / total_incoming_msat
            in_p65 = cache.get(f"incoming_p65_7d:{pubkey}")
            if in_p65 is None:
                series_entry = cache.get(f"incoming_series_7d:{pubkey}")
                if isinstance(series_entry, dict) and series_entry.get("vals"):
                    vs = sorted(series_entry["vals"])
                    pos = 0.65 * (len(vs) - 1)
                    lo, hi = int(pos), int(math.ceil(pos))
                    in_p65 = vs[lo] if lo == hi else vs[lo]*(hi - pos) + vs[hi]*(pos - lo)
                    cache[f"incoming_p65_7d:{pubkey}"] = in_p65
            if share >= (avg_share * 1.8) and bias_ema <= - (SOURCE_BIAS_MIN - 0.03):
                cand_label = "source"
                cand_conf  = min(1.0, cand_conf + 0.10)

        # Histerese de classe
        if cand_label != "unknown":
            if class_label == "unknown":
                class_label, class_conf = cand_label, cand_conf
            else:
                if cand_label != class_label:
                    if cand_conf >= (class_conf + CLASS_CONF_HYSTERESIS):
                        class_label, class_conf = cand_label, cand_conf
                else:
                    class_conf = min(1.0, 0.5*class_conf + 0.5*cand_conf)

        # tags da classe (para relatório)
        class_tags = []
        if class_label == "sink":   class_tags.append(TAG_SINK)
        if class_label == "source": class_tags.append(TAG_SOURCE)
        if class_label == "router": class_tags.append(TAG_ROUTER)
        if class_label == "unknown": class_tags.append(TAG_UNKNOWN)
        if DEBUG_TAGS:
            class_tags.append(f"🧭bias{bias_ema:+.2f}")
            class_tags.append(f"🧭{class_label}:{class_conf:.2f}")

        # --- Escalada por persistência (ANTES do ajuste de liquidez) ---
        streak = state.get(cid, {}).get("low_streak", 0)
        if PERSISTENT_LOW_ENABLE:
            if out_ratio < PERSISTENT_LOW_THRESH:
                streak += 1
            else:
                streak = 0

            if streak >= PERSISTENT_LOW_STREAK_MIN:
                bump_acc = (streak - PERSISTENT_LOW_STREAK_MIN + 1) * PERSISTENT_LOW_BUMP
                bump_acc = min(PERSISTENT_LOW_MAX, max(0.0, bump_acc))

                # ⬇️ NOVO: não inflar em stale-drain (sem base)
                baseline_val_persist = state.get(cid, {}).get("baseline_fwd7d", 0) or 0
                if (streak >= EXTREME_DRAIN_STREAK) and (baseline_val_persist <= 2):
                    bump_acc = 0.0

                bump_mult = 1.0 + bump_acc
                bump_mode = "seed"
                if PERSISTENT_LOW_OVER_CURRENT_ENABLE and target <= local_ppm:
                    target = max(
                        target,
                        int(math.ceil(local_ppm * bump_mult)),
                        local_ppm + int(PERSISTENT_LOW_MIN_STEP_PPM or 0)
                    )
                    bump_mode = "over_current"
                else:
                    target = int(math.ceil(target * bump_mult))

                if new_inbound:
                    target = target_base
                report.append(f"📈 Persistência: {alias} ({cid}) streak {streak} ⇒ bump {bump_acc*100:.0f}% ({bump_mode})")

        # --- Ajuste por liquidez ---
        if out_ratio < LOW_OUTBOUND_THRESH:
            if not new_inbound:
                target *= (1.0 + LOW_OUTBOUND_BUMP)
        elif out_ratio > HIGH_OUTBOUND_THRESH:
            target *= (1.0 - HIGH_OUTBOUND_CUT)
            if fwd_count == 0 and out_ratio > 0.60:
                target *= (1.0 - IDLE_EXTRA_CUT)

        # Discovery hard-drop
        st_prev2 = state.get(cid, {}) or {}
        first_seen_ts2 = st_prev2.get("first_seen_ts", int(time.time()))
        days_since_first = (int(time.time()) - first_seen_ts2) / 86400 if first_seen_ts2 else 999
        discovery_hard = (
            DISCOVERY_ENABLE and
            fwd_count <= DISCOVERY_FWDS_MAX and
            out_ratio > DISCOVERY_OUT_MIN and
            days_since_first >= DISCOVERY_HARDDROP_DAYS_NO_BASE and
            (state.get(cid, {}).get("baseline_fwd7d", 0) or 0) == 0
        )
        if discovery_hard:
            target_base = seed_used + DISCOVERY_HARDDROP_COLCHAO
            target = min(target, target_base + (target - (seed_used + COLCHAO_PPM)) * 0.5)

        # --- BOOSTS que RESPEITAM o step cap ---
        surge_tag = ""
        top_tag = ""
        negm_tag = ""
        boosted_target = target

        if (not new_inbound) and SURGE_ENABLE and out_ratio < SURGE_LOW_OUT_THRESH:
            lack = max(0.0, (SURGE_LOW_OUT_THRESH - out_ratio) / SURGE_LOW_OUT_THRESH)
            surge_bump = min(SURGE_BUMP_MAX, SURGE_K * lack)
            if surge_bump > 0:
                boosted_target = max(boosted_target, int(math.ceil(target * (1.0 + surge_bump))))
                surge_tag = f"⚡surge+{int(surge_bump*100)}%"

        if TOP_REVENUE_SURGE_ENABLE and rev_share >= TOP_OUTFEE_SHARE and out_ratio < 0.30:
            boosted_target = max(boosted_target, int(math.ceil(target * (1.0 + TOP_REVENUE_SURGE_BUMP))))
            top_tag = f"👑top+{int(TOP_REVENUE_SURGE_BUMP*100)}%"

        if NEG_MARGIN_SURGE_ENABLE and margin_ppm_7d < 0 and fwd_count >= NEG_MARGIN_MIN_FWDS:
            boosted_target = max(boosted_target, int(math.ceil(target * (1.0 + NEG_MARGIN_SURGE_BUMP))))
            negm_tag = f"💹negm+{int(NEG_MARGIN_SURGE_BUMP*100)}%"

        # clamp do alvo e guarda "no-down while low"
        target = clamp_ppm(boosted_target)

        pl_tags = []
        if (not new_inbound) and out_ratio < PERSISTENT_LOW_THRESH and target < local_ppm:
            target = local_ppm
            pl_tags.append("🙅‍♂️no-down-low")

        # ---- STEP CAP dinâmico ----
        cap_frac = STEP_CAP
        if DYNAMIC_STEP_CAP_ENABLE:
            if out_ratio < 0.03:
                cap_frac = max(cap_frac, STEP_CAP_LOW_005)
            elif out_ratio < 0.05:
                cap_frac = max(cap_frac, STEP_CAP_LOW_010)
            if fwd_count == 0 and out_ratio > 0.60:
                cap_frac = max(cap_frac, STEP_CAP_IDLE_DOWN)

        # Discovery mode
        discovery_hit = False
        if DISCOVERY_ENABLE and fwd_count <= DISCOVERY_FWDS_MAX and out_ratio > DISCOVERY_OUT_MIN:
            discovery_hit = True
            cap_frac = max(cap_frac, STEP_CAP_IDLE_DOWN)
            if discovery_hard and local_ppm > target:
                cap_frac = max(cap_frac, DISCOVERY_HARDDROP_CAP_FRAC)

        # NEW INBOUND: step cap maior só para reduzir
        if new_inbound and local_ppm > target:
            cap_frac = max(cap_frac, NEW_INBOUND_DOWN_STEPCAP_FRAC)

        # Extreme drain mode — acelera SUBIDAS
        if EXTREME_DRAIN_ENABLE:
            low_streak_val = state.get(cid, {}).get("low_streak", 0)
            baseline_val = state.get(cid, {}).get("baseline_fwd7d", 0) or 0
            if (low_streak_val >= EXTREME_DRAIN_STREAK and
                out_ratio < EXTREME_DRAIN_OUT_MAX and
                baseline_val > 0 and
                target > local_ppm):
                cap_frac = max(cap_frac, EXTREME_DRAIN_STEP_CAP)
                STEP_MIN_STEP_PPM_UP = max(STEP_MIN_STEP_PPM, EXTREME_DRAIN_MIN_STEP_PPM)
            else:
                STEP_MIN_STEP_PPM_UP = STEP_MIN_STEP_PPM
        else:
            STEP_MIN_STEP_PPM_UP = STEP_MIN_STEP_PPM

        # bônus leve de reatividade em ROUTER
        if class_label == "router":
            cap_frac = min(0.50, cap_frac + ROUTER_STEP_CAP_BONUS)

        raw_step_ppm = target if local_ppm == 0 else apply_step_cap2(
            local_ppm, target, cap_frac,
            STEP_MIN_STEP_PPM if target <= local_ppm else STEP_MIN_STEP_PPM_UP
        )

        # Circuit breaker
        state_all = state.get(cid, {})
        last_ppm  = state_all.get("last_ppm", local_ppm)
        last_dir  = state_all.get("last_dir", "flat")
        last_ts   = state_all.get("last_ts", 0)
        baseline  = state_all.get("baseline_fwd7d", None)

        if last_dir == "up" and (now_ts - last_ts) <= CB_GRACE_DAYS*24*3600 and baseline:
            if baseline > 0 and fwd_count < baseline * CB_DROP_RATIO:
                raw_step_ppm = clamp_ppm(int(raw_step_ppm * (1.0 - CB_REDUCE_STEP)))
                report.append(f"🧯 CB: {alias} ({cid}) fwd {fwd_count}<{int(baseline*CB_DROP_RATIO)} ⇒ recuo {int(CB_REDUCE_STEP*100)}%")

        # Piso de rebal conforme REBAL_COST_MODE
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

        # Em SOURCE, desabilitar outrate floor
        if class_label == "source" and SOURCE_DISABLE_OUTRATE_FLOOR:
            outrate_floor_active = False
        
        # NEW: se não houve forwards na janela, não aplica outrate floor
        if fwd_count == 0:
            outrate_floor_active = False

        if outrate_floor_active and fwd_count >= OUTRATE_FLOOR_MIN_FWDS and out_ppm_7d > 0:
            outrate_floor = clamp_ppm(math.ceil(out_ppm_7d * outrate_factor))
            floor_ppm = max(floor_ppm, outrate_floor)

        # Cap do floor pelo seed (evita piso "absurdo")
        floor_ppm = min(floor_ppm, clamp_ppm(int(math.ceil(seed_used * REBAL_FLOOR_SEED_CAP_FACTOR))))

        # SINK — piso adicional e não descer abaixo de fração do seed
        if class_label == "sink":
            extra = clamp_ppm(int(math.ceil((base_cost_for_margin or 0) * SINK_EXTRA_FLOOR_MARGIN)))
            floor_ppm = max(floor_ppm, extra)
            floor_ppm = max(floor_ppm, clamp_ppm(int(seed_used * SINK_MIN_OVER_SEED_FRAC)))

        # ⬇️ NOVO: em discovery, desligar piso de rebal (deixa só o MIN_PPM)
        if discovery_hit:
            floor_ppm = max(MIN_PPM, min(floor_ppm, MIN_PPM))

        # Cálculo final com piso
        final_ppm = max(raw_step_ppm, floor_ppm)

        # Revenue floor — piso adicional por tráfego (super-rotas)
        if REVFLOOR_ENABLE:
            baseline_eff = state.get(cid, {}).get("baseline_fwd7d", 0) or 0
            if baseline_eff >= REVFLOOR_BASELINE_THRESH:
                revfloor_seed = clamp_ppm(int(max(seed_used * 0.40, REVFLOOR_MIN_PPM_ABS)))
                final_ppm = max(final_ppm, revfloor_seed)

        # SOURCE — preferir alvo mais baixo relativo ao seed (quando for QUEDA)
        if class_label == "source" and final_ppm < local_ppm:
            pref = clamp_ppm(int(seed_used * SOURCE_SEED_TARGET_FRAC))
            final_ppm = min(final_ppm, pref)

        # Clamp final com teto local por canal (barreira suave)
        local_max = min(MAX_PPM, max(800, int(seed_used * 1.8)))
        final_ppm = max(MIN_PPM, min(local_max, int(round(final_ppm))))

        # Telemetria: bateu no MAX_PPM global?
        if final_ppm == MAX_PPM:
            max_hits += 1

        # Diagnóstico
        diag_tags = []
        if raw_step_ppm != target:
            dir_same = ((target > local_ppm and raw_step_ppm > local_ppm) or
                        (target < local_ppm and raw_step_ppm < local_ppm))
            if dir_same:
                diag_tags.append("⛔stepcap")

        if final_ppm == floor_ppm and target != floor_ppm:
            diag_tags.append("🧱floor-lock")

        if final_ppm == local_ppm and target != local_ppm and floor_ppm <= local_ppm:
            diag_tags.append("⛔stepcap-lock")

        # marcações de contexto
        discovery_hit and diag_tags.append("🧪discovery")
        for t in (surge_tag, top_tag, negm_tag):
            if t: diag_tags.append(t)
        if new_inbound:
            diag_tags.append(NEW_INBOUND_TAG)

        if REVFLOOR_ENABLE and (state.get(cid, {}).get("baseline_fwd7d", 0) or 0) >= REVFLOOR_BASELINE_THRESH:
            if final_ppm < max(int(seed_used * 0.90), int(max(seed_used * 0.40, REVFLOOR_MIN_PPM_ABS))):
                diag_tags.append("⚠️subprice")
        if (state.get(cid, {}).get("low_streak", 0) or 0) >= EXTREME_DRAIN_STREAK and (state.get(cid, {}).get("baseline_fwd7d", 0) or 0) <= 2:
            diag_tags.append("💤stale-drain")

        if DEBUG_TAGS:
            diag_tags.append(f"🔍t{target}/r{raw_step_ppm}/f{floor_ppm}")
        status_tags = []  # já foi montado acima; só para clareza de ordem
        all_tags = class_tags + seed_tags + diag_tags

        # ====== MÍNIMO REAL: sanear local < MIN_PPM ======
        # Fazemos antes do gate de microupdate/cooldown.
        if local_ppm < MIN_PPM:
            # Vamos forçar aplicação do mínimo, sem segurar por cooldown/microupdate.
            final_ppm = max(final_ppm, MIN_PPM)
            all_tags.append("🩹min-fix")

        new_ppm = final_ppm

        # Aplica/relata
        seed_note = f"{int(seed_used)}" + (" (cap)" if seed_flags else "")
        dir_for_emoji = "up" if new_ppm > local_ppm else ("down" if new_ppm < local_ppm else "flat")
        emo = "🔺" if dir_for_emoji == "up" else ("🔻" if dir_for_emoji == "down" else "⏸️")

        # Gate anti-microupdate
        push_forced_by_floor = (floor_ppm > local_ppm and new_ppm > local_ppm)
        will_push = True
        if new_ppm != local_ppm and not push_forced_by_floor:
            delta_ppm = abs(new_ppm - local_ppm)
            rel = delta_ppm / max(1, local_ppm)
            if delta_ppm < BOS_PUSH_MIN_ABS_PPM and rel < BOS_PUSH_MIN_REL_FRAC:
                will_push = False
                all_tags.append("🧘hold-small")

        # se estamos corrigindo MIN_PPM, força push
        if local_ppm < MIN_PPM and new_ppm >= MIN_PPM:
            will_push = True

        # === COOLDOWN / HISTERÉSE ===
        st_prev  = state.get(cid, {})
        last_ts  = st_prev.get("last_ts", 0)
        hours_since = (int(time.time()) - last_ts) / 3600 if last_ts else 999
        fwds_at_change = st_prev.get("fwds_at_change", 0)
        fwds_since = max(0, fwd_count - fwds_at_change)

        if APPLY_COOLDOWN_ENABLE and new_ppm != local_ppm and not push_forced_by_floor:
            # em discovery e QUEDA, não aplicar cooldown
            if discovery_hit and new_ppm < local_ppm:
                pass
            elif not (new_inbound and new_ppm < local_ppm):
                need = COOLDOWN_HOURS_UP if new_ppm > local_ppm else COOLDOWN_HOURS_DOWN
                if hours_since < need and fwds_since < COOLDOWN_FWDS_MIN:
                    will_push = False
                    all_tags.append(f"⏳cooldown{int(need)}h")
                if (COOLDOWN_PROFIT_DOWN_ENABLE and new_ppm < local_ppm):
                    if (margin_ppm_7d > COOLDOWN_PROFIT_MARGIN_MIN and fwd_count >= COOLDOWN_PROFIT_FWDS_MIN):
                        need2 = max(need, COOLDOWN_HOURS_DOWN)
                        if hours_since < need2:
                            will_push = False
                            all_tags.append(f"⏳cooldown-profit{int(need2)}h")

        # DRY context: --dry-run ou excluido
        act_dry = dry_run or is_excluded

        # Persistência de classificação/bias no STATE
        if not dry_run:  # em execução real, sempre persiste classe (mesmo excluído)
            st_for_save = state.get(cid, {}).copy()
            st_for_save["bias_ema"]    = float(bias_ema)
            st_for_save["class_label"] = class_label
            st_for_save["class_conf"]  = float(class_conf)
            state[cid] = st_for_save
        elif dry_run and DRYRUN_SAVE_CLASS and not is_excluded:
            # Em dry-run, persistir SOMENTE campos de classe (sem mexer em last_ppm/ts/etc.)
            st_for_save = state.get(cid, {}).copy()
            st_for_save.setdefault("first_seen_ts", int(time.time()))
            st_for_save["bias_ema"]    = float(bias_ema)
            st_for_save["class_label"] = class_label
            st_for_save["class_conf"]  = float(class_conf)
            state[cid] = st_for_save

        if new_ppm != local_ppm and will_push:
            delta = new_ppm - local_ppm
            pct = (abs(delta) / local_ppm * 100.0) if local_ppm > 0 else 0.0
            dstr = f"{'+' if delta>0 else ''}{delta} ({pct:.1f}%)"

            if act_dry:
                if is_excluded and not EXCL_DRY_VERBOSE:
                    report.append(f"✅{emo} {alias}: 🚷excl-dry")
                    if new_ppm > local_ppm: excl_dry_up += 1
                    else: excl_dry_down += 1
                else:
                    action = f"DRY set {local_ppm}→{new_ppm} ppm {dstr}"
                    new_dir = dir_for_emoji
                    excl_note = " 🚷excl-dry" if is_excluded else ""
                    report.append(
                        f"✅{emo} {alias}:{excl_note} {action} | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{seed_note} | floor≥{floor_ppm} | marg≈{margin_ppm_7d} | rev_share≈{rev_share:.2f} | {' '.join(all_tags)}"
                    )
                    if is_excluded:
                        if new_ppm > local_ppm: excl_dry_up += 1
                        else: excl_dry_down += 1
                    else:
                        # >>> NOVO: contabiliza no resumo também em dry-run
                        if new_ppm > local_ppm: changed_up += 1
                        else: changed_down += 1
            else:
                try:
                    if pubkey:
                        bos_set_fee_ppm(pubkey, new_ppm)
                        action = f"set {local_ppm}→{new_ppm} ppm {dstr}"
                        new_dir = dir_for_emoji

                        # baseline EMA (70/30) se houver amostra >0
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
                            "fwds_at_change": fwd_count,
                            # garantir persistência da classificação
                            "bias_ema": float(bias_ema),
                            "class_label": class_label,
                            "class_conf": float(class_conf),
                        })
                        state[cid] = st
                    else:
                        action = "❌ sem pubkey/snapshot p/ aplicar"
                        new_dir = "flat"
                except Exception as e:
                    action = f"❌ erro ao setar: {e}"
                    new_dir = "flat"

                excl_note = " 🚷excl-dry" if is_excluded else ""
                report.append(
                    f"✅{emo} {alias}:{excl_note} {action} | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{seed_note} | floor≥{floor_ppm} | marg≈{margin_ppm_7d} | rev_share≈{rev_share:.2f} | {' '.join(all_tags)}"
                )
                if is_excluded:
                    if new_ppm > local_ppm: excl_dry_up += 1
                    else: excl_dry_down += 1
                else:
                    if new_ppm > local_ppm: changed_up += 1
                    else: changed_down += 1

        else:
            # mantém (ou micro-update/cooldown segurou)
            if not dry_run:  # em execução real, sempre persiste campos de classe
                st = state.get(cid, {}).copy()
                st.setdefault("first_seen_ts", int(time.time()))
                st["low_streak"] = streak if PERSISTENT_LOW_ENABLE else 0
                st["last_seed"] = float(seed_used)
                st["bias_ema"] = float(bias_ema)
                st["class_label"] = class_label
                st["class_conf"] = float(class_conf)
                state[cid] = st
            elif dry_run and DRYRUN_SAVE_CLASS and not is_excluded:
                st = state.get(cid, {}).copy()
                st.setdefault("first_seen_ts", int(time.time()))
                st["bias_ema"] = float(bias_ema)
                st["class_label"] = class_label
                st["class_conf"] = float(class_conf)
                state[cid] = st

            if is_excluded and not EXCL_DRY_VERBOSE:
                report.append(f"🫤⏸️ {alias}: 🚷excl-dry")
                excl_dry_kept += 1
            else:
                excl_note = " 🚷excl-dry" if is_excluded else ""
                report.append(
                    f"🫤⏸️ {alias}:{excl_note} mantém {local_ppm} ppm | alvo {target} | out_ratio {out_ratio:.2f} | out_ppm7d≈{int(out_ppm_7d)} | seed≈{seed_note} | floor≥{floor_ppm} | marg≈{margin_ppm_7d} | rev_share≈{rev_share:.2f} | {' '.join(all_tags)}"
                )
                if is_excluded:
                    excl_dry_kept += 1
                else:
                    kept += 1

    # resumo na 2ª linha do relatório
    summary = f"📊 up {changed_up} | down {changed_down} | flat {kept} | low_out {low_out_count} | offline {offline_skips} | max_hits {max_hits}"
    if SHARDING_ENABLE:
        summary += f" | shard_skips {shard_skips}"
    if (excl_dry_up + excl_dry_down + excl_dry_kept) > 0:
        summary += f" | excl_dry up {excl_dry_up} | down {excl_dry_down} | flat {excl_dry_kept}"
    report.insert(1, summary)

    if unmatched > 0:
        report.append(f"ℹ️  {unmatched} canal(is) sem snapshot por scid/chan_point (out_ratio=0.50 por fallback). Cheque versão do lncli e permissões.")

    save_json(CACHE_PATH, cache)
    # Em dry-run, salvamos STATE se DRYRUN_SAVE_CLASS=True (apenas campos de classe foram atualizados)
    if (not dry_run) or DRYRUN_SAVE_CLASS:
        save_json(STATE_PATH, state)

    msg = "\n".join(report)
    print(msg)
    if not dry_run:
        tg_send_big(msg)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Auto fee LND (Amboss seed com guard, EMA, ponderação por entrada, liquidez, boosts respeitando step cap, piso robusto, persistência over-current, discovery, circuit-breaker, SHARDING, COOLDOWN, 🌱normalize de canais novos inbound e 🧭classificação dinâmica sink/source/router; DRY p/ exclusão; DEBUG tags)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula: não aplica BOS; grava apenas campos de classificação se DRYRUN_SAVE_CLASS=True"
    )
    # Controle de verbosidade para canais excluídos
    excl = parser.add_mutually_exclusive_group()
    excl.add_argument("--excl-dry-verbose", action="store_true", help="Mostra detalhes completos nos canais excluídos (padrão).")
    excl.add_argument("--excl-dry-tag-only", action="store_true", help="Mostra somente a tag 🚷excl-dry (sem métricas).")
    args = parser.parse_args()

    # aplica flags de CLI (prioridade maior que variável de ambiente)
    if args.excl_dry_verbose:
        EXCL_DRY_VERBOSE = True
    if args.excl_dry_tag_only:
        EXCL_DRY_VERBOSE = False

    main(dry_run=args.dry_run)

