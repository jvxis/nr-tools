#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
import json
import math
import os
import re
import sqlite3
import time
from typing import Dict, Any, List, Optional, Tuple

# =========================
# HARD-CODE CONFIG
# =========================

# Telegram
TELEGRAM_TOKEN = "SEU TOKEN TELEGRAM"
CHATID         = "SEU CHAT ID"

# LNDg API
LNDG_BASE_URL = "http://ip-maquina-lndg:8889"
username      = "lndg-admin"
password      = "senha_lndg"

CHANNELS_API_URL   = f"{LNDG_BASE_URL}/api/channels/?is_open=true&is_active=true"
CHANNEL_UPDATE_URL = f"{LNDG_BASE_URL}/api/channels/{{chan_id}}/"

# LNDg DB (para custo de rebal 7d)
DB_PATH = "/home/admin/lndg/data/db.sqlite3"
LOOKBACK_DAYS = 7

# AutoFee cache/state (decisões + persistir cooldown AR)
CACHE_PATH = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH = "/home/admin/.cache/auto_fee_state.json"

# Origem dos parâmetros do AutoFee (arquivo oficial) + cache opcional
AUTO_FEE_FILE          = "/home/admin/nr-tools/brln-autofee pro/brln-autofee-pro.py"
AUTO_FEE_PARAMS_CACHE  = "/home/admin/nr-tools/brln-autofee pro/params_autofee.json"   # opcional

# Log local (auditoria)
LOG_PATH = "/home/admin/lndg_ar_actions.log"

# Histerese no alvo de outbound (pontos percentuais)
HYSTERESIS_PP = 5

# Alvos seguros
OUT_TARGET_MIN = 10   # %
OUT_TARGET_MAX = 90   # %

# Margem de segurança sobre o custo 7d para considerar "lucrativo"
REBAL_SAFETY = 1.05
# Buffer extra perto do breakeven para evitar flapping
BREAKEVEN_BUFFER = 0.03  # +3%

# Gate de preço: só deixa ligar AR se local_ppm*ar_max_cost ≥ remote_ppm*(1+buffer)
AR_PRICE_BUFFER = 0.10  # 10% de folga sobre a remota

# Confiabilidade do custo por canal (7d)
MIN_REBAL_VALUE_SAT = 400_000  # igual ao AutoFee
MIN_REBAL_COUNT     = 3        # e pelo menos 3 rebalances

# Cooldown mínimo entre trocas de ON/OFF (dwell time)
MIN_DWELL_HOURS = 0.5

# >>> NOVO: habilita o bypass de cooldown para desligar imediatamente em condições seguras
FAST_OFF_ENABLE = True

# Bias por classe (fallback quando não houver bias_ema no state)
CLASS_BIAS = {
    "sink":   +0.12,  # +12pp no alvo de outbound
    "router":  0.00,
    "source": -0.10,
    "unknown": 0.00,
}

# Teto do viés dinâmico obtido do AutoFee (bias_ema) em pontos percentuais
BIAS_MAX_PP = 12
BIAS_HARD_CLAMP_PP = 20  # clamp duro de segurança

def demand_bonus(baseline_fwds: int) -> float:
    """Bônus por demanda (baseline de fwds 7d salvo no state do AutoFee)."""
    if baseline_fwds >= 150:
        return 0.08   # +8pp
    if baseline_fwds >= 50:
        return 0.04   # +4pp
    return 0.00

# ===== Exclusões: exatamente como você colou =====
EXCLUSION_LIST = [
#'891080507132936203', #LNBig Edge3 16M

]

# (Opcional) Forçar canais como "source" mesmo se o AutoFee disser outra coisa
FORCE_SOURCE_LIST = set([
    #"982400445448257541", # Aldebaran
])

# =========================
# Utilidades
# =========================

def clamp_ratio(x: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))

def chunk_text(s: str, n: int = 4000):
    while s:
        if len(s) <= n:
            yield s; break
        cut = s.rfind("\n", 0, n)
        if cut == -1: cut = n
        yield s[:cut]; s = s[cut:]

async def tg_send(session: aiohttp.ClientSession, text: str):
    if not TELEGRAM_TOKEN or not CHATID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for part in chunk_text(text, 4000):
        try:
            await session.post(url, json={"chat_id": CHATID, "text": part}, timeout=20)
        except Exception:
            pass

async def safe_text(r: aiohttp.ClientResponse) -> str:
    try: return await r.text()
    except Exception: return "<no-body>"

def now_ts() -> int:
    return int(time.time())

def log_append(entry: Dict[str, Any]) -> None:
    try:
        line = json.dumps({"ts": now_ts(), **entry}, ensure_ascii=False)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path: str, data: Dict[str, Any]) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# =========================
# Parâmetros do AutoFee (direto do brln-autofee-2.py)
# =========================

AF_PARAM_NAMES = [
    "LOW_OUTBOUND_THRESH",
    "HIGH_OUTBOUND_THRESH",
    "LOW_OUTBOUND_BUMP",
    "HIGH_OUTBOUND_CUT",
    "IDLE_EXTRA_CUT",
]

_FLOAT_RE = re.compile(r"^\s*([A-Z_]+)\s*=\s*([0-9]*\.?[0-9]+)\s*(#.*)?$", re.MULTILINE)

def parse_autofee_py(path: str) -> Dict[str, float]:
    params: Dict[str, float] = {}
    try:
        with open(path, "r") as f:
            text = f.read()
        for m in _FLOAT_RE.finditer(text):
            name, val = m.group(1), m.group(2)
            if name in AF_PARAM_NAMES:
                try:
                    params[name] = float(val)
                except Exception:
                    pass
    except Exception:
        return {}
    return params

def load_autofee_params() -> Dict[str, float]:
    """
    1) Tenta cache JSON (se existir).
    2) Lê e parseia o brln-autofee-2.py.
    3) Se conseguiu parsear, escreve/atualiza o cache.
    4) Fallbacks sensatos.
    """
    params = {}
    # passo 1: cache
    if os.path.isfile(AUTO_FEE_PARAMS_CACHE):
        params.update(load_json(AUTO_FEE_PARAMS_CACHE))

    # passo 2: arquivo oficial
    parsed = parse_autofee_py(AUTO_FEE_FILE)
    if parsed:
        params.update(parsed)
        # passo 3: atualiza cache
        try:
            save_json(AUTO_FEE_PARAMS_CACHE, params)
        except Exception:
            pass

    # passo 4: fallbacks
    params.setdefault("LOW_OUTBOUND_THRESH", 0.05)
    params.setdefault("HIGH_OUTBOUND_THRESH", 0.20)
    params.setdefault("LOW_OUTBOUND_BUMP",   0.01)
    params.setdefault("HIGH_OUTBOUND_CUT",   0.01)
    params.setdefault("IDLE_EXTRA_CUT",      0.005)

    return params

# =========================
# LNDg API
# =========================

async def fetch_all_channels(session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
    url = CHANNELS_API_URL
    out: List[Dict[str, Any]] = []
    auth = aiohttp.BasicAuth(username, password)
    while url:
        async with session.get(url, auth=auth) as r:
            if r.status != 200:
                raise RuntimeError(f"GET {url} -> {r.status}: {await safe_text(r)}")
            data = await r.json()
            if isinstance(data, dict) and "results" in data:
                out.extend(data.get("results", []))
                url = data.get("next")
            elif isinstance(data, list):
                out.extend(data); url = None
            else:
                out.extend(data.get("results", []))
                url = data.get("next")
    return out

async def update_channel(session: aiohttp.ClientSession, chan_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = CHANNEL_UPDATE_URL.format(chan_id=chan_id)
    auth = aiohttp.BasicAuth(username, password)
    async with session.put(url, json=payload, auth=auth) as r:
        if r.status == 200:
            return await r.json()
        if r.status in (400, 405):
            async with session.patch(url, json=payload, auth=auth) as rp:
                if rp.status == 200:
                    return await rp.json()
                raise RuntimeError(f"PATCH {url} -> {rp.status}: {await safe_text(rp)}")
        raise RuntimeError(f"PUT {url} -> {r.status}: {await safe_text(r)}")

# =========================
# DB LNDg → custo rebal 7d
# =========================

def to_sqlite_str(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(sep=' ', timespec='seconds')

def ppm(total_fee_sat: int, total_amt_sat: int) -> float:
    if total_amt_sat <= 0: return 0.0
    return (total_fee_sat / total_amt_sat) * 1_000_000.0

def load_rebal_costs(db_path: str, lookback_days: int = 7):
    t2 = datetime.now(timezone.utc)
    t1 = t2 - timedelta(days=lookback_days)
    t1s, t2s = to_sqlite_str(t1), to_sqlite_str(t2)

    sql = """
    SELECT rebal_chan, value, fee
    FROM gui_payments
    WHERE rebal_chan IS NOT NULL
      AND chan_out IS NOT NULL
      AND creation_date BETWEEN ? AND ?
    """
    per_value = {}
    per_fee   = {}
    per_count = {}
    total_v = 0
    total_f = 0

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    for (rebal_chan, value, fee) in cur.execute(sql, (t1s, t2s)).fetchall():
        cid = str(rebal_chan)
        v = int(value or 0)
        f = int(fee or 0)
        per_value[cid] = per_value.get(cid, 0) + v
        per_fee[cid]   = per_fee.get(cid,   0) + f
        per_count[cid] = per_count.get(cid, 0) + 1
        total_v += v
        total_f += f
    conn.close()

    per_cost_ppm = {}
    for cid, v in per_value.items():
        f = per_fee.get(cid, 0)
        per_cost_ppm[cid] = ppm(f, v)

    global_cost_ppm = ppm(total_f, total_v)
    return per_cost_ppm, global_cost_ppm, per_value, per_count

# =========================
# AutoFee state helpers
# =========================

def get_class_label(state: Dict[str, Any], cid: str) -> str:
    return (state.get(cid) or {}).get("class_label", "unknown")

def get_baseline(state: Dict[str, Any], cid: str) -> int:
    return int((state.get(cid) or {}).get("baseline_fwd7d", 0) or 0)

def get_last_seed(state: Dict[str, Any], cid: str) -> Optional[float]:
    v = (state.get(cid) or {}).get("last_seed", None)
    try:
        return float(v) if v is not None else None
    except Exception:
        return None

def get_last_switch(state: Dict[str, Any], cid: str) -> Optional[int]:
    return int((state.get(cid) or {}).get("ar_last_switch_ts", 0) or 0)

def set_last_switch(state: Dict[str, Any], cid: str, new_state: bool) -> None:
    st = state.get(cid) or {}
    st["ar_last_switch_ts"] = now_ts()
    st["ar_last_state"] = bool(new_state)
    state[cid] = st

def get_bias_pp_from_state(state: Dict[str, Any], cid: str, cls: str) -> float:
    """
    Converte bias_ema [-1..+1] do STATE_PATH em pontos percentuais de viés.
    Fallback: usa CLASS_BIAS quando não houver bias_ema (inclui 'unknown').
    Retorna em 'pp' (ex.: +12 para +12%).
    """
    rec = state.get(cid) or {}
    ema = rec.get("bias_ema", None)
    if isinstance(ema, (int, float)):
        pp = float(ema) * float(BIAS_MAX_PP)
        pp = max(-BIAS_HARD_CLAMP_PP, min(BIAS_HARD_CLAMP_PP, pp))
        return pp
    return float(int(round(CLASS_BIAS.get(cls, 0.0) * 100)))

# =========================
# Decisão / Alvos / Razões
# =========================

def compute_targets(global_out_ratio: float, cls: str, baseline: int,
                    state: Dict[str, Any], cid: str) -> Tuple[int, int]:
    """
    Alvo de outbound por canal = global + viés (bias_ema → pp) + bônus por demanda.
    Mantém clamp [OUT_TARGET_MIN, OUT_TARGET_MAX] e limita a global+5pp (teto suave).
    """
    base  = global_out_ratio
    bias_pp = get_bias_pp_from_state(state, cid, cls)  # em pontos percentuais
    bias = bias_pp / 100.0
    bonus = demand_bonus(baseline)
    out = min(base + bias + bonus, global_out_ratio + 0.05)  # teto suave: +5pp acima do global
    out = clamp_ratio(out, OUT_TARGET_MIN/100.0, OUT_TARGET_MAX/100.0)
    out_pct = int(round(out * 100))
    in_pct  = 100 - out_pct
    return out_pct, in_pct

def profitable(local_ppm: int, remote_ppm: int,
               ch_cost_ppm: Optional[float], global_cost_ppm: Optional[float]) -> Tuple[bool, str]:
    """Lucro se margem_ppm ≥ custo_7d * safety * (1+buffer). Usa custo por canal; fallback no global."""
    margin = max(0, int(local_ppm) - int(remote_ppm))
    base_cost = None
    fonte = "indisp"
    if ch_cost_ppm is not None and ch_cost_ppm > 0:
        base_cost = ch_cost_ppm
        fonte = "canal"
    elif global_cost_ppm is not None and global_cost_ppm > 0:
        base_cost = global_cost_ppm
        fonte = "global"
    else:
        return False, f"💵 margem {margin}ppm < custo_7d indisponível"

    need_base = math.ceil(base_cost * REBAL_SAFETY)
    need = math.ceil(need_base * (1.0 + BREAKEVEN_BUFFER))
    ok = margin >= need
    mot = (f"💵 margem {margin}ppm {'≥' if ok else '<'} "
           f"🧮 custo_7d({fonte}) {int(base_cost)}ppm × {REBAL_SAFETY:.2f} + {int(BREAKEVEN_BUFFER*100)}% ≈ {need}ppm")
    return ok, mot

def price_gate_ok(local_ppm: int, remote_ppm: int, ar_max_cost: float) -> Tuple[bool, str]:
    """
    Gate ‘primeiro princípio’: mesmo no teto de custo do AR (ar_max_cost%),
    a sua taxa local precisa cobrir a remota com folga.
    """
    try:
        cap_mult = float(ar_max_cost or 0.0) / 100.0
    except Exception:
        cap_mult = 0.0
    lhs = local_ppm * cap_mult
    rhs = remote_ppm * (1.0 + AR_PRICE_BUFFER)
    ok = lhs >= rhs
    mot = (f"🔒 price-gate: local {local_ppm}ppm × ar_max_cost {ar_max_cost:.0f}% "
           f"{'≥' if ok else '<'} remota {remote_ppm}ppm × (1+{int(AR_PRICE_BUFFER*100)}%) "
           f"→ {lhs:.0f} {'≥' if ok else '<'} {rhs:.0f}")
    return ok, mot

def looks_like_source(local_ppm: int, remote_ppm: int, out_ratio: float, baseline: int) -> bool:
    """Heurística conservadora para identificar SOURCE."""
    if local_ppm == 0:
        return True
    if out_ratio >= 0.50 and local_ppm <= max(1, remote_ppm // 4):
        return True
    return False

def hysteresis_decision(out_ratio: float, tgt_out_pct: int, current_on: bool, can_profit: bool,
                        cls: str, religa_out_thresh: float, baseline: int) -> Tuple[Optional[bool], str]:
    """
    Liga/desliga com histerese ±HYSTERESIS_PP. Respeita política de SOURCE (AR OFF).
    Retorna (novo_estado_ou_None, razão)
    """
    # Política de SOURCE: nunca liga (mesmo drenado)
    if cls == "source":
        if current_on:
            return False, "🔻 desliga (source: política AR sempre OFF)"
        return None, "🚫 não liga (source: política AR sempre OFF)"

    low  = (tgt_out_pct - HYSTERESIS_PP)/100.0
    high = (tgt_out_pct + HYSTERESIS_PP)/100.0
    r = out_ratio

    if current_on:
        if (r >= high) and can_profit:
            return False, f"🔻 desliga: acima do alvo+his ({r:.2f} ≥ {high:.2f})"
        if not can_profit:
            return False, f"🔻 desliga: não lucrativo pelo custo_7d"
        return None, "⏸️ mantém: dentro da faixa de histerese"
    else:
        # drenado o suficiente? (usa limiar do AutoFee para ‘re-ligar’)
        if (r <= religa_out_thresh) and can_profit:
            return True, f"🔺 liga: drenado (≤ {religa_out_thresh:.2f}) e lucrativo"
        if not can_profit:
            return None, "🚫 não liga: margem não cobre custo_7d"
        return None, "⏸️ não liga: dentro da faixa de histerese"

# >>> NOVO: helper para ignorar cooldown apenas para DESLIGAR em condições seguras
def bypass_dwell_for_off(ar_current: bool,
                         proposed_toggle: Optional[bool],
                         out_ratio: float,
                         tgt_out_pct: int,
                         price_ok: bool,
                         prof_ok: bool,
                         fill_lock_active: bool) -> bool:
    """
    Permite desligar imediatamente (ignora cooldown) se:
      - já encheu acima do alvo+his, OU
      - price-gate reprovado, OU
      - lucro 7d insuficiente,
    e não estamos em fill-lock (ou seja, não estamos deliberadamente enchendo).
    """
    if not FAST_OFF_ENABLE:
        return False
    if not ar_current or proposed_toggle is not False:
        return False
    if fill_lock_active:
        return False
    high = (tgt_out_pct + HYSTERESIS_PP) / 100.0
    if (out_ratio >= high) or (not price_ok) or (not prof_ok):
        return True
    return False

# =========================
# MAIN
# =========================

async def main():
    timeout = aiohttp.ClientTimeout(total=40)
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # 0) Carregar parâmetros do AutoFee diretamente do arquivo oficial
        af_params = load_autofee_params()
        religa_out_thresh = float(af_params.get("LOW_OUTBOUND_THRESH", 0.05))

        # 1) Canais
        channels = await fetch_all_channels(session)
        if not channels:
            await tg_send(session, "⚠️ LNDg: nenhum canal retornado.")
            return

        # 2) Outbound global
        total_cap = sum(int(c.get("capacity") or 0) for c in channels)
        total_loc = sum(int(c.get("local_balance") or 0) for c in channels)
        global_out_ratio = (total_loc / total_cap) if total_cap else 0.0

        # 3) Custos de rebal 7d
        per_cost_ppm, global_cost_ppm, per_value_sat, per_count = load_rebal_costs(DB_PATH, LOOKBACK_DAYS)

        # 4) AutoFee cache/state
        cache_af = load_json(CACHE_PATH)  # reservado para evoluções
        state_af = load_json(STATE_PATH)

        changes = 0
        msgs: List[str] = []
        now = now_ts()

        for ch in channels:
            cid = str(ch.get("chan_id") or "")
            if not cid or cid in EXCLUSION_LIST:
                continue

            cap   = max(1, int(ch.get("capacity") or 0))
            loc   = int(ch.get("local_balance") or 0)
            out_r = loc / cap

            alias       = ch.get("alias") or "unknown"
            local_ppm   = int(ch.get("local_fee_rate") or 0)
            remote_ppm  = int(ch.get("remote_fee_rate") or 0)
            ar_current  = bool(ch.get("auto_rebalance", False))
            out_t_cur   = int(ch.get("ar_out_target") or -1)
            in_t_cur    = int(ch.get("ar_in_target") or -1)
            ar_max_cost = float(ch.get("ar_max_cost") or 0.0)

            # Classe/demanda do AutoFee
            cls       = get_class_label(state_af, cid)
            baseline  = get_baseline(state_af, cid)
            seed_last = get_last_seed(state_af, cid)

            # SOURCE override (manual/heurístico)
            cls_eff = cls
            if (cid in FORCE_SOURCE_LIST) or looks_like_source(local_ppm, remote_ppm, out_r, baseline):
                if cls != "source":
                    log_append({"type":"class_override","cid":cid,"alias":alias,"from":cls,"to":"source"})
                cls_eff = "source"

            # Alvos (global + viés + demanda) — se source, compute só para exibir; gate abaixo força AR OFF.
            out_tgt, in_tgt = compute_targets(global_out_ratio, cls_eff, baseline, state_af, cid)
            if cls_eff == "source":
                out_tgt, in_tgt = 5, 95  # política source: alvo fixo 5/95

            # Custo 7d: usar canal só se confiável; senão global
            ch_val_sat = int(per_value_sat.get(cid, 0))
            ch_cnt     = int(per_count.get(cid, 0))
            ch_cost_raw = per_cost_ppm.get(cid)
            use_ch_cost = (ch_cost_raw is not None and ch_cost_raw > 0 and ch_val_sat >= MIN_REBAL_VALUE_SAT and ch_cnt >= MIN_REBAL_COUNT)
            ch_cost = ch_cost_raw if use_ch_cost else None

            # Gates de decisão
            price_ok, price_mot = price_gate_ok(local_ppm, remote_ppm, ar_max_cost)
            prof_ok,  prof_mot  = profitable(local_ppm, remote_ppm, ch_cost, global_cost_ppm)

            # ---------- FILL-LOCK: se estamos enchendo, travar alvo e manter AR ON até atingir o alvo ----------
            fill_lock_active = False
            locked_out_tgt = out_tgt
            if cls_eff != "source" and ar_current:
                if out_r < (out_tgt / 100.0):
                    fill_lock_active = True
                    locked_out_tgt = max(out_tgt, int(math.ceil(out_r * 100)))
                    # enquanto não atingiu o alvo: não permitir desligar por preço/custo (apenas informativo)
                    price_mot = price_mot + " | 🔒 fill-lock ignora price-gate até atingir alvo"
                    prof_mot  = prof_mot  + " | 🔒 fill-lock ignora custo_7d até atingir alvo"

            # ---------- CAP-LOCK: se o novo alvo ficou menor do que o out_ratio atual, suba o alvo para o out_ratio ----------
            cap_lock_active = False
            cap_locked_out_tgt = out_tgt
            if cls_eff != "source" and (out_r > (out_tgt / 100.0)):
                cap_lock_active = True
                cap_locked_out_tgt = int(math.ceil(out_r * 100))

            # 2) histerese / re-liga drenado — respeitando fill-lock, cap-lock e política de source
            toggle: Optional[bool] = None
            hys_mot = ""
            if cls_eff == "source":
                toggle = (False if ar_current else None)
                hys_mot = "🔻 desliga/segura OFF: source (AR sempre OFF)"
            elif fill_lock_active:
                toggle = None
                hys_mot = f"🔒 fill-lock ativo: enchendo até out≥{out_tgt}% (agora {out_r:.2f})"
            else:
                if not price_ok:
                    toggle = (False if ar_current else None)
                    hys_mot = "🔻 desliga/segura OFF: price-gate reprovado"
                else:
                    toggle, hys_mot = hysteresis_decision(
                        out_ratio=out_r,
                        tgt_out_pct=out_tgt,
                        current_on=ar_current,
                        can_profit=prof_ok,
                        cls=cls_eff,
                        religa_out_thresh=religa_out_thresh,
                        baseline=baseline
                    )

            # 3) cooldown mínimo entre trocas
            if toggle is not None:
                last_sw = get_last_switch(state_af, cid) or 0
                hours_since = (now - last_sw)/3600 if last_sw else 999
                if hours_since < MIN_DWELL_HOURS:
                    # >>> FAST-OFF: ignora cooldown para DESLIGAR em condições seguras
                    if bypass_dwell_for_off(
                        ar_current=ar_current,
                        proposed_toggle=toggle,
                        out_ratio=out_r,
                        tgt_out_pct=out_tgt,
                        price_ok=price_ok,
                        prof_ok=prof_ok,
                        fill_lock_active=fill_lock_active
                    ):
                        hys_mot = (hys_mot + " | ⚡ fast-off: ignorando cooldown").strip()
                    else:
                        toggle = None
                        hys_mot = f"⏳ cooldown: aguarde {MIN_DWELL_HOURS}h após última troca"

            # Montar payload — prioridade: fill-lock > cap-lock > normal
            payload = {}
            if toggle is not None:
                payload["auto_rebalance"] = toggle

            if fill_lock_active:
                desired_out_target = locked_out_tgt
                lock_tag = " (fill-lock)"
            elif cap_lock_active:
                desired_out_target = cap_locked_out_tgt
                lock_tag = " (🧷 cap-lock)"
            else:
                desired_out_target = out_tgt
                lock_tag = ""

            if out_t_cur != desired_out_target:
                payload["ar_out_target"] = desired_out_target
            if in_t_cur  != in_tgt:
                payload["ar_in_target"]  = in_tgt

            did_change = False
            if payload:
                try:
                    await update_channel(session, cid, payload)
                    did_change = True
                    changes += 1

                    if "auto_rebalance" in payload:
                        set_last_switch(state_af, cid, bool(payload["auto_rebalance"]))
                    
                    # Estado do AR após esta atualização (se não veio no payload, mantém o atual)
                    ar_state_after = payload.get("auto_rebalance", ar_current)
                    ar_state_txt = "ON" if ar_state_after else "OFF"
                    
                    # debug do bias aplicado
                    bias_pp_dbg = get_bias_pp_from_state(state_af, cid, cls_eff)

                    bits = []
                    bits.append(f"⚙️ AutoFee params: Low Outbound Thresh={religa_out_thresh:.2f}")
                    bits.append(f"🎛️ bias={bias_pp_dbg:+.0f}pp (ema)")
                    bits.append(price_mot)                 # 🔒 price-gate
                    bits.append(prof_mot)                  # 💵 vs 🧮
                    if hys_mot:
                        bits.append(hys_mot)               # 🔺/🔻/⏳/🚫/🔒/⚡
                    if cap_lock_active and not fill_lock_active:
                        bits.append("🧷 cap-lock: preserva liquidez, evita virar fonte de rebal")
                    bits.append(f"🏷️{cls_eff} • 📈 base7d {baseline}")
                    if seed_last is not None:
                        bits.append(f"🌱 seed≈{int(seed_last)}ppm")
                    if use_ch_cost:
                        bits.append(f"💸 custo_7d(canal)≈{int(ch_cost_raw)}ppm (vol≈{ch_val_sat:,}; cnt={ch_cnt})")
                    elif global_cost_ppm and global_cost_ppm > 0:
                        bits.append(f"🌐 custo_7d(global)≈{int(global_cost_ppm)}ppm")
                    else:
                        bits.append("🌐 custo_7d: sem amostra")

                    mot = " | ".join(bits)
                    action_txt = ("🟢 ON" if payload.get("auto_rebalance", ar_current)
                                  else "🛑 OFF") if "auto_rebalance" in payload else "🛠️ TARGET"

                    msg = (
                        f"✅ {action_txt} {alias} ({cid})\n"
                        f"• 🔌 AR: {ar_state_txt}\n"
                        f"• 📊 out_ratio {out_r:.2f} • 💱 fee L/R {local_ppm}/{remote_ppm}ppm • 🧮 ar_max_cost {ar_max_cost:.0f}%\n"
                        f"• 🎯 alvo out/in {desired_out_target}/{in_tgt}%"
                        f"{' (source 5/95)' if cls_eff=='source' else lock_tag}\n"
                        f"• 🔎 motivo: {mot}"
                    )
                    msgs.append(msg)

                    # log
                    log_append({
                        "type": "update",
                        "cid": cid, "alias": alias,
                        "out_ratio": round(out_r, 4),
                        "local_ppm": local_ppm, "remote_ppm": remote_ppm,
                        "ar_max_cost": ar_max_cost,
                        "targets": {"out": desired_out_target, "in": in_tgt},
                        "action": action_txt,
                        "price_gate_ok": price_ok,
                        "profitable": prof_ok,
                        "class": cls_eff,
                        "baseline": baseline,
                        "used_cost": ("channel" if use_ch_cost else "global"),
                        "cost_ppm": int(ch_cost_raw if use_ch_cost else (global_cost_ppm or 0)),
                        "vol_sat_7d": ch_val_sat,
                        "count_7d": ch_cnt,
                        "fill_lock": fill_lock_active,
                        "cap_lock": cap_lock_active,
                        "autofee_params": af_params,
                        "bias_pp": bias_pp_dbg
                    })
                except Exception as e:
                    err = f"❌ {alias} ({cid}) erro ao atualizar: {e}"
                    msgs.append(err)
                    log_append({"type":"error","cid":cid,"alias":alias,"error":str(e)})

            # alvo mudou mas AR não? ainda assim setamos target e logamos
            if (not did_change) and (out_t_cur != desired_out_target or in_t_cur != in_tgt):
                try:
                    await update_channel(session, cid, {"ar_out_target": desired_out_target, "ar_in_target": in_tgt})
                    changes += 1
                    bias_pp_dbg = get_bias_pp_from_state(state_af, cid, cls_eff)
                    ar_state_txt = "ON" if ar_current else "OFF"

                    txt = (
                        f"✅ 🛠️ TARGET {alias} ({cid})\n"
                        f"• 🔌 AR: {ar_state_txt}\n"
                        f"• 📊 out_ratio {out_r:.2f} • 💱 fee L/R {local_ppm}/{remote_ppm}ppm • 🧮 ar_max_cost {ar_max_cost:.0f}%\n"
                        f"• 🎯 alvo out/in {desired_out_target}/{in_tgt}%"
                        f"{' (source 5/95)' if cls_eff=='source' else lock_tag}\n"
                        f"• 🔎 motivo: {price_gate_ok(local_ppm, remote_ppm, ar_max_cost)[1]} | "
                        f"{profitable(local_ppm, remote_ppm, ch_cost, global_cost_ppm)[1]} | "
                        f"⚙️ Low Outbound = {religa_out_thresh:.2f} | 🎛️ bias={bias_pp_dbg:+.0f}pp (ema)"
                    )
                    msgs.append(txt)
                    log_append({
                        "type":"targets_only","cid":cid,"alias":alias,
                        "targets":{"out":desired_out_target,"in":in_tgt},
                        "class":cls_eff,"baseline":baseline,
                        "fill_lock": fill_lock_active,
                        "cap_lock": cap_lock_active,
                        "autofee_params": af_params,
                        "bias_pp": bias_pp_dbg
                    })
                except Exception as e:
                    err = f"❌ {alias} ({cid}) erro ao setar TARGET: {e}"
                    msgs.append(err)
                    log_append({"type":"error","cid":cid,"alias":alias,"error":str(e)})

        # salvar STATE_PATH se houve troca (cooldown persistido)
        if changes > 0:
            save_json(STATE_PATH, state_af)

        header = (f"⚡ LNDg AR Trigger v2  "
                  f"| chans={len(channels)} "
                  f"| global_out={global_out_ratio:.2f} "
                  f"| rebal7d≈{int(global_cost_ppm or 0)}ppm "
                  f"| mudanças={changes}")
        body = "\n\n".join(msgs) if msgs else "Sem mudanças."
        await tg_send(session, f"{header}\n{body}")

if __name__ == "__main__":
    asyncio.run(main())
