#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, sqlite3, datetime, time, math, argparse
from collections import defaultdict
from zoneinfo import ZoneInfo
import re
from pathlib import Path

try:
    import requests  # para Telegram
except Exception:
    requests = None  # manter execução sem Telegram


# === Telegram (HARD-CODE p/ testes; opcional) ===
TELEGRAM_TOKEN = "SEU BOT TOKEN"  # <<< PREENCHER
TELEGRAM_CHAT  = "SEU CHAT ID"   # <<< PREENCHER

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

# === paths (ajuste se necessário) ===
DB_PATH     = '/home/admin/lndg/data/db.sqlite3'
CACHE_PATH  = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH  = "/home/admin/.cache/auto_fee_state.json"
OVERRIDES   = "/home/admin/nr-tools/brln-autofee pro/autofee_overrides.json"

# log do autofee que MOSTRA o que foi aplicado
AUTOFEE_LOG_PATH = "/home/admin/autofee-apply.log"

# controle de versão centralizado (texto)
# 1ª linha útil (não vazia e não começando com '#') = versão ativa
# Ex.: 0.3.1 - Ajuste de pisos, bugfix de budget, melhora no PEG
VERSIONS_FILE = "/home/admin/nr-tools/brln-autofee pro/versions.txt"

LOOKBACK_DAYS = 7

# =========================
# Heurística pró-lucro (camadas)
# =========================
SAT_PROFIT_MIN       = 50_000   # lucro em sats/7d considerado “ok”
PPM_WORSE            = -120     # profit_ppm_est “muito ruim”
PPM_MEH              = -60      # levemente ruim
REQUIRED_GOOD_STREAK = 2        # janelas positivas consecutivas p/ “afrouxar”

# === limites de segurança para knobs ===
LIMITS = {
    "STEP_CAP":                (0.02, 0.15),
    "SURGE_K":                 (0.20, 0.90),
    "SURGE_BUMP_MAX":          (0.10, 0.50),
    "PERSISTENT_LOW_BUMP":     (0.03, 0.12),
    "PERSISTENT_LOW_MAX":      (0.10, 0.40),
    "REBAL_FLOOR_MARGIN":      (0.05, 0.30),
    "REVFLOOR_MIN_PPM_ABS":    (100, 400),
    "OUTRATE_FLOOR_FACTOR":    (0.85, 1.35),
    "BOS_PUSH_MIN_ABS_PPM":    (5, 20),
    "BOS_PUSH_MIN_REL_FRAC":   (0.01, 0.06),
    "COOLDOWN_HOURS_DOWN":     (3, 18),
    "COOLDOWN_HOURS_UP":       (1, 12),
    "REBAL_BLEND_LAMBDA":      (0.0, 1.0),
    "NEG_MARGIN_SURGE_BUMP":   (0.05, 0.20),
}

DEFAULTS = {
    "STEP_CAP": 0.05,
    "SURGE_K": 0.50,
    "SURGE_BUMP_MAX": 0.20,
    "PERSISTENT_LOW_BUMP": 0.05,
    "PERSISTENT_LOW_MAX": 0.20,
    "REBAL_FLOOR_MARGIN": 0.10,
    "REVFLOOR_MIN_PPM_ABS": 140,
    "OUTRATE_FLOOR_FACTOR": 1.0,
    "BOS_PUSH_MIN_ABS_PPM": 15,
    "BOS_PUSH_MIN_REL_FRAC": 0.04,
    "COOLDOWN_HOURS_DOWN": 6,
    "COOLDOWN_HOURS_UP": 3,
    "REBAL_BLEND_LAMBDA": 0.30,
    "NEG_MARGIN_SURGE_BUMP": 0.05,
}

# Anti-ratchet (higiene)
MIN_HOURS_BETWEEN_CHANGES = 6
REQUIRED_BAD_STREAK = 1   # se quiser reagir no 1º dia ruim, troque para 1

# Orçamento diário de variação ABSOLUTA por chave
DAILY_CHANGE_BUDGET = {
    "OUTRATE_FLOOR_FACTOR": 0.08,
    "REVFLOOR_MIN_PPM_ABS": 40,
    "REBAL_FLOOR_MARGIN":   0.08,
    "STEP_CAP":             0.03,
    "SURGE_K":              0.15,
    "SURGE_BUMP_MAX":       0.08,
    "PERSISTENT_LOW_BUMP":  0.02,
    "PERSISTENT_LOW_MAX":   0.06,
    "BOS_PUSH_MIN_ABS_PPM": 6,
    "BOS_PUSH_MIN_REL_FRAC":0.01,
    "COOLDOWN_HOURS_UP":    3,
    "COOLDOWN_HOURS_DOWN":  4,
    "REBAL_BLEND_LAMBDA":   0.20,
    "NEG_MARGIN_SURGE_BUMP": 0.03,
}
META_PATH = "/home/admin/nr-tools/brln-autofee pro/autofee_meta.json"

# =========================
# Versão centralizada (leitura do topo da lista)
# =========================
def read_version_info(path: str):
    info = {"version": "0.0.0", "desc": ""}
    try:
        p = Path(path)
        if not p.exists():
            return info
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^\s*([0-9]+(?:\.[0-9]+){1,2})\s*-\s*(.+)$", line)
                if m:
                    info["version"] = m.group(1).strip()
                    info["desc"] = m.group(2).strip()
                else:
                    info["version"] = line
                    info["desc"] = ""
                break
    except Exception:
        pass
    return info

# =========================
# Utilidades
# =========================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except:
        pass
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

def ppm(total_fee_sat, total_amt_sat):
    if total_amt_sat <= 0: return 0.0
    return (total_fee_sat / total_amt_sat) * 1_000_000.0

def to_sqlite_str(dt):
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat(sep=' ', timespec='seconds')

# =========================
# KPIs e sintomas
# =========================
def get_7d_kpis():
    t2 = datetime.datetime.now(datetime.timezone.utc)
    t1 = t2 - datetime.timedelta(days=LOOKBACK_DAYS)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("""
    SELECT amt_out_msat, fee FROM gui_forwards
    WHERE forward_date BETWEEN ? AND ?
    """, (to_sqlite_str(t1), to_sqlite_str(t2)))
    f_rows = cur.fetchall()

    out_amt_sat = 0
    out_fee_sat = 0
    for a_msat, fee in f_rows:
        out_amt_sat += int((a_msat or 0)/1000)
        out_fee_sat += int(fee or 0)

    cur.execute("""
    SELECT value, fee FROM gui_payments
    WHERE rebal_chan IS NOT NULL
      AND chan_out IS NOT NULL
      AND creation_date BETWEEN ? AND ?
    """, (to_sqlite_str(t1), to_sqlite_str(t2)))
    p_rows = cur.fetchall()

    rb_val = 0
    rb_fee = 0
    for v, f in p_rows:
        rb_val += int(v or 0)
        rb_fee += int(f or 0)

    conn.close()

    kpis = {
        "out_fee_sat": out_fee_sat,
        "out_amt_sat": out_amt_sat,
        "rebal_fee_sat": rb_fee,
        "rebal_amt_sat": rb_val,
        "out_ppm7d": ppm(out_fee_sat, out_amt_sat),
        "rebal_cost_ppm7d": ppm(rb_fee, rb_val)
    }
    kpis["profit_sat"] = kpis["out_fee_sat"] - kpis["rebal_fee_sat"]
    kpis["profit_ppm_est"] = kpis["out_ppm7d"] - (kpis["rebal_cost_ppm7d"] if kpis["rebal_cost_ppm7d"]>0 else 0)
    return kpis

def read_symptoms_from_logs():
    counts = { "floor_lock": 0, "no_down_low": 0, "hold_small": 0, "cb_trigger": 0, "discovery": 0 }
    log_path = Path(AUTOFEE_LOG_PATH)
    if not log_path.exists():
        return counts
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            size = f.tell()
            back = min(size, 200_000)
            f.seek(size - back)
            tail = f.read()
    except Exception:
        return counts
    header_re = re.compile(r'(?:DRY[-\s]*RUN\s*)?[\u2699\uFE0F\u200D\uFE0F]*\s*AutoFee\s*\|\s*janela\s*\d+d', re.IGNORECASE)
    hits = list(header_re.finditer(tail))
    block = tail[hits[-1].start():] if hits else tail
    m = re.search(r"Symptoms:\s*\{([^}]*)\}", block)
    if m:
        try:
            inner = "{" + m.group(1) + "}"
            inner = inner.replace("'", '"')
            parsed = json.loads(inner)
            for k in counts.keys():
                if k in parsed and isinstance(parsed[k], (int, float)):
                    counts[k] = int(parsed[k])
        except Exception:
            pass
    counts["floor_lock"] += len(re.findall(r'🧱floor-lock', block))
    counts["no_down_low"] += len(re.findall(r'🙅‍♂️no-down-low', block))
    counts["hold_small"] += len(re.findall(r'🧘hold-small', block))
    counts["cb_trigger"] += len(re.findall(r'🧯\s*CB:', block))
    counts["discovery"]  += len(re.findall(r'🧪discovery', block))
    return counts

# =========================
# Lógica de ajuste
# =========================
def adjust(overrides, kpis, symptoms):
    changed = {}
    prof_sat = kpis["profit_sat"]
    out_ppm  = kpis["out_ppm7d"]
    rebal_ppm= kpis["rebal_cost_ppm7d"]
    profit_ppm_est = kpis["profit_ppm_est"]

    def get(k):
        return float(overrides.get(k, DEFAULTS.get(k))) if isinstance(DEFAULTS.get(k), (int,float)) else overrides.get(k, DEFAULTS.get(k))

    STEP_CAP              = get("STEP_CAP")
    SURGE_K               = get("SURGE_K")
    SURGE_BUMP_MAX        = get("SURGE_BUMP_MAX")
    PERSISTENT_LOW_BUMP   = get("PERSISTENT_LOW_BUMP")
    PERSISTENT_LOW_MAX    = get("PERSISTENT_LOW_MAX")
    REBAL_FLOOR_MARGIN    = get("REBAL_FLOOR_MARGIN")
    REVFLOOR_MIN_PPM_ABS  = get("REVFLOOR_MIN_PPM_ABS")
    OUTRATE_FLOOR_FACTOR  = get("OUTRATE_FLOOR_FACTOR")
    BOS_PUSH_MIN_ABS_PPM  = get("BOS_PUSH_MIN_ABS_PPM")
    BOS_PUSH_MIN_REL_FRAC = get("BOS_PUSH_MIN_REL_FRAC")
    COOLDOWN_DOWN         = get("COOLDOWN_HOURS_DOWN")
    COOLDOWN_UP           = get("COOLDOWN_HOURS_UP")
    REBAL_BLEND_LAMBDA    = get("REBAL_BLEND_LAMBDA")
    NEG_MARGIN_SURGE_BUMP = get("NEG_MARGIN_SURGE_BUMP")

    # Classificação de severidade
    if prof_sat <= 0:
        bad_tier = "hard"
    elif prof_sat < SAT_PROFIT_MIN and profit_ppm_est < PPM_MEH:
        bad_tier = "medium"
    elif profit_ppm_est < PPM_WORSE:
        bad_tier = "medium"
    else:
        bad_tier = "ok"

    rebal_overpriced = (rebal_ppm >= out_ppm) or ((out_ppm - rebal_ppm) < 50)

    # =========================
    # Plano A (como já era): empurra pisos quando ruim + rebal caro
    # =========================
    if bad_tier in ("hard", "medium") and rebal_overpriced:
        incr = 1.0 if bad_tier == "hard" else 0.66
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR + 0.03*incr, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REVFLOOR_MIN_PPM_ABS = int(clamp(REVFLOOR_MIN_PPM_ABS + 10*incr, *LIMITS["REVFLOOR_MIN_PPM_ABS"]))
        REBAL_FLOOR_MARGIN   = clamp(REBAL_FLOOR_MARGIN + 0.02*incr, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REVFLOOR_MIN_PPM_ABS"] = REVFLOOR_MIN_PPM_ABS
        changed["REBAL_FLOOR_MARGIN"]   = REBAL_FLOOR_MARGIN

        NEG_MARGIN_SURGE_BUMP = clamp(NEG_MARGIN_SURGE_BUMP + (0.02 if bad_tier=="hard" else 0.01), *LIMITS["NEG_MARGIN_SURGE_BUMP"])
        changed["NEG_MARGIN_SURGE_BUMP"] = NEG_MARGIN_SURGE_BUMP

    # =========================
    # Alívio de floor-lock mesmo em bad (quando MUITO alto)
    # =========================
    if symptoms.get("floor_lock", 0) >= 100 and profit_ppm_est < 0:
        # pequeno respiro para tentar destravar rota, respeitando limites
        new_rebal_floor = clamp(REBAL_FLOOR_MARGIN - 0.01, *LIMITS["REBAL_FLOOR_MARGIN"])
        if new_rebal_floor != REBAL_FLOOR_MARGIN:
            REBAL_FLOOR_MARGIN = new_rebal_floor
            changed["REBAL_FLOOR_MARGIN"] = REBAL_FLOOR_MARGIN

    # =========================
    # Regras existentes
    # =========================
    if symptoms.get("floor_lock", 0) >= 15 and bad_tier == "ok":
        REBAL_FLOOR_MARGIN = clamp(REBAL_FLOOR_MARGIN - 0.02, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["REBAL_FLOOR_MARGIN"] = REBAL_FLOOR_MARGIN

    if symptoms.get("no_down_low", 0) >= 10:
        PERSISTENT_LOW_BUMP = clamp(PERSISTENT_LOW_BUMP + 0.01, *LIMITS["PERSISTENT_LOW_BUMP"])
        SURGE_K = clamp(SURGE_K + 0.05, *LIMITS["SURGE_K"])
        SURGE_BUMP_MAX = clamp(SURGE_BUMP_MAX + 0.03, *LIMITS["SURGE_BUMP_MAX"])
        changed["PERSISTENT_LOW_BUMP"] = PERSISTENT_LOW_BUMP
        changed["SURGE_K"] = SURGE_K
        changed["SURGE_BUMP_MAX"] = SURGE_BUMP_MAX

    if (symptoms.get("no_down_low", 0) >= 10) and (profit_ppm_est < 0):
        PERSISTENT_LOW_MAX = clamp(PERSISTENT_LOW_MAX + 0.02, *LIMITS["PERSISTENT_LOW_MAX"])
        changed["PERSISTENT_LOW_MAX"] = PERSISTENT_LOW_MAX

    if symptoms.get("hold_small", 0) >= 20 and prof_sat > 0:
        BOS_PUSH_MIN_ABS_PPM  = int(clamp(BOS_PUSH_MIN_ABS_PPM - 2, *LIMITS["BOS_PUSH_MIN_ABS_PPM"]))
        BOS_PUSH_MIN_REL_FRAC = clamp(BOS_PUSH_MIN_REL_FRAC - 0.005, *LIMITS["BOS_PUSH_MIN_REL_FRAC"])
        changed["BOS_PUSH_MIN_ABS_PPM"]  = BOS_PUSH_MIN_ABS_PPM
        changed["BOS_PUSH_MIN_REL_FRAC"] = BOS_PUSH_MIN_REL_FRAC

    if symptoms.get("cb_trigger", 0) >= 8:
        STEP_CAP = clamp(STEP_CAP - 0.01, *LIMITS["STEP_CAP"])
        COOLDOWN_DOWN = clamp(COOLDOWN_DOWN + 2, *LIMITS["COOLDOWN_HOURS_DOWN"])
        changed["STEP_CAP"] = STEP_CAP
        changed["COOLDOWN_HOURS_DOWN"] = COOLDOWN_DOWN
        COOLDOWN_UP = clamp(COOLDOWN_UP + 1, *LIMITS["COOLDOWN_HOURS_UP"])
        changed["COOLDOWN_HOURS_UP"] = COOLDOWN_UP

    if (prof_sat >= SAT_PROFIT_MIN and profit_ppm_est > -40 and symptoms.get("floor_lock", 0) >= 25):
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR - 0.01, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REBAL_FLOOR_MARGIN   = clamp(REBAL_FLOOR_MARGIN - 0.01, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REBAL_FLOOR_MARGIN"]   = REBAL_FLOOR_MARGIN

    # =========================
    # Plano B (fallback): se os 3 pisos estão no TETO e ainda estamos em bad, empurre knobs de surge/persistência
    # =========================
    at_out_floor_max = abs(OUTRATE_FLOOR_FACTOR - LIMITS["OUTRATE_FLOOR_FACTOR"][1]) < 1e-12
    at_revfloor_max  = abs(float(REVFLOOR_MIN_PPM_ABS) - float(LIMITS["REVFLOOR_MIN_PPM_ABS"][1])) < 1e-12
    at_rebal_marg_max= abs(REBAL_FLOOR_MARGIN - LIMITS["REBAL_FLOOR_MARGIN"][1]) < 1e-12

    if bad_tier in ("hard", "medium") and (at_out_floor_max and at_revfloor_max and at_rebal_marg_max):
        # Só empurre se ainda houver margem real nesses knobs
        new_surge_k = clamp(SURGE_K + 0.05, *LIMITS["SURGE_K"])
        if new_surge_k != SURGE_K:
            SURGE_K = new_surge_k
            changed.setdefault("SURGE_K", SURGE_K)

        new_surge_max = clamp(SURGE_BUMP_MAX + 0.03, *LIMITS["SURGE_BUMP_MAX"])
        if new_surge_max != SURGE_BUMP_MAX:
            SURGE_BUMP_MAX = new_surge_max
            changed.setdefault("SURGE_BUMP_MAX", SURGE_BUMP_MAX)

        new_pl_bump = clamp(PERSISTENT_LOW_BUMP + 0.01, *LIMITS["PERSISTENT_LOW_BUMP"])
        if new_pl_bump != PERSISTENT_LOW_BUMP:
            PERSISTENT_LOW_BUMP = new_pl_bump
            changed.setdefault("PERSISTENT_LOW_BUMP", PERSISTENT_LOW_BUMP)

        if profit_ppm_est < 0:
            new_pl_max = clamp(PERSISTENT_LOW_MAX + 0.02, *LIMITS["PERSISTENT_LOW_MAX"])
            if new_pl_max != PERSISTENT_LOW_MAX:
                PERSISTENT_LOW_MAX = new_pl_max
                changed.setdefault("PERSISTENT_LOW_MAX", PERSISTENT_LOW_MAX)

    return changed


# =========================
# Anti-ratchet helpers
# =========================
def load_meta():
    try:
        if os.path.exists(META_PATH):
            with open(META_PATH, "r") as f:
                meta = json.load(f)
                meta.setdefault("last_change_ts", 0)
                meta.setdefault("bad_streak", 0)
                meta.setdefault("good_streak", 0)
                meta.setdefault("daily_budget", {})
                meta.setdefault("last_day", None)
                return meta
    except:
        pass
    return {"last_change_ts": 0, "bad_streak": 0, "good_streak": 0, "daily_budget": {}, "last_day": None}

def save_meta(meta):
    os.makedirs(os.path.dirname(META_PATH), exist_ok=True)
    with open(path := META_PATH, "w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)

def can_change_now(meta):
    now = int(time.time())
    hours = (now - int(meta.get("last_change_ts", 0))) / 3600.0
    return hours >= MIN_HOURS_BETWEEN_CHANGES

def update_bad_streak(meta, profit_ppm_est):
    if profit_ppm_est < 0:
        meta["bad_streak"] = int(meta.get("bad_streak", 0)) + 1
    else:
        meta["bad_streak"] = 0

def update_good_streak(meta, prof_sat, profit_ppm_est):
    if profit_ppm_est > 0 and prof_sat >= SAT_PROFIT_MIN:
        meta["good_streak"] = int(meta.get("good_streak", 0)) + 1
    else:
        meta["good_streak"] = 0

def rollover_daily_budget_if_needed(meta):
    """Garante reset do budget diário, mesmo sem alterações propostas/aplicadas."""
    day = datetime.datetime.now(LOCAL_TZ).date().isoformat()
    if meta.get("last_day") != day:
        meta["daily_budget"] = {}
        meta["last_day"] = day

def enforce_daily_budget(current_overrides, proposed_new_values, meta):
    day = datetime.datetime.now(LOCAL_TZ).date().isoformat()
    if meta.get("last_day") != day:
        meta["daily_budget"] = {}
        meta["last_day"] = day
    allowed = {}
    for k, new_abs in proposed_new_values.items():
        old_abs = current_overrides.get(k, DEFAULTS.get(k))
        if old_abs is None:
            old_abs = DEFAULTS.get(k)
        try:
            old_abs = float(old_abs)
            new_abs = float(new_abs)
        except Exception:
            allowed[k] = new_abs
            continue
        diff = new_abs - old_abs
        if diff == 0:
            continue
        limit = DAILY_CHANGE_BUDGET.get(k)
        if not limit:
            allowed[k] = new_abs
            continue
        used = float(meta["daily_budget"].get(k, 0.0))
        room = max(0.0, limit - used)
        step = diff
        if room <= 0:
            continue
        if abs(step) > room:
            step = math.copysign(room, step)
        final_val = old_abs + step
        allowed[k] = final_val
        meta["daily_budget"][k] = used + abs(step)
    return allowed

def apply_limits(proposed):
    out = {}
    for k, v in proposed.items():
        if k in LIMITS:
            lo, hi = LIMITS[k]
            out[k] = clamp(float(v), lo, hi) if isinstance(v, (int, float)) else v
        else:
            out[k] = v
    return out

def explain_discarded_changes(cur, pre, post, meta):
    """
    Retorna dict {knob: motivo} para propostas que existiam em `pre` mas sumiram em `post`.
    Motivos possíveis:
      - "at_limit": valor atual já está no limite (ou proposta clampou no mesmo valor)
      - "no_budget": sem espaço no budget diário
      - "no_diff": proposta igual ao valor atual
      - "filtered": filtrado por lógica residual
    """
    reasons = {}
    used = (meta or {}).get("daily_budget", {})
    for k, new_val in pre.items():
        old_val = cur.get(k, DEFAULTS.get(k))
        # desapareceu após budget?
        if k in post:
            continue
        try:
            old_f = float(old_val)
            new_f = float(new_val)
        except Exception:
            continue

        # sem diferença efetiva
        if abs(new_f - old_f) < 1e-12:
            reasons[k] = "no_diff"
            continue

        # limite
        if k in LIMITS:
            lo, hi = LIMITS[k]
            clamped = max(lo, min(hi, new_f))
            if abs(clamped - old_f) < 1e-12:
                reasons[k] = "at_limit"
                continue

        # sem budget
        lim = DAILY_CHANGE_BUDGET.get(k)
        if lim is not None:
            used_k = float(used.get(k, 0.0))
            room = max(0.0, lim - used_k)
            if room <= 0:
                reasons[k] = "no_budget"
                continue

        # fallback
        reasons[k] = "filtered"
    return reasons

# =========================
# Telegram helpers (hard-coded)
# =========================
def tg_enabled():
    return (TELEGRAM_TOKEN not in (None, "")) and (TELEGRAM_CHAT not in (None, "")) and (requests is not None)

def tg_send(text: str, disable_web_preview: bool=True):
    if not tg_enabled():
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4096
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)] or [text]
    for part in chunks:
        try:
            requests.post(url, json={
                "chat_id": TELEGRAM_CHAT,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_web_preview
            }, timeout=10)
        except Exception:
            pass

def fmt_num(n, zero_dash=False):
    try:
        if isinstance(n, (int, float)):
            if abs(n) >= 1000 and abs(n) < 1_000_000:
                return f"{n:,.0f}".replace(",", ".")
            if abs(n) >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if isinstance(n, float):
                return f"{n:.2f}"
            return str(n)
        if zero_dash and (n == 0 or n == "0"):
            return "–"
        return str(n)
    except Exception:
        return str(n)

def build_tg_message(version_info, now_local, kpis, symptoms, proposed, meta, dry_run, cooldown_blocked, discard_reasons=None):
    v = version_info.get("version","0.0.0")
    vdesc = version_info.get("desc","")
    header_icon = "🧪" if dry_run else "🔧"
    title = f"{header_icon} AI Param Tuner v{v}"
    ts = now_local.strftime("%Y-%m-%d %H:%M:%S")

    kp = (
        f"• <b>KPI 7d</b>: "
        f"out_fee=<code>{fmt_num(kpis.get('out_fee_sat',0))}</code> sat | "
        f"out_amt=<code>{fmt_num(kpis.get('out_amt_sat',0))}</code> sat | "
        f"rebal_fee=<code>{fmt_num(kpis.get('rebal_fee_sat',0))}</code> sat\n"
        f"• ppm_out=<code>{fmt_num(kpis.get('out_ppm7d',0.0))}</code> | "
        f"ppm_rebal=<code>{fmt_num(kpis.get('rebal_cost_ppm7d',0.0))}</code> | "
        f"profit_sat=<code>{fmt_num(kpis.get('profit_sat',0))}</code> | "
        f"profit_ppm≈<code>{fmt_num(kpis.get('profit_ppm_est',0.0))}</code>"
    )

    sy = (
        f"• <b>Symptoms</b>: "
        f"🧱={symptoms.get('floor_lock',0)} | "
        f"🙅‍♂️={symptoms.get('no_down_low',0)} | "
        f"🧘={symptoms.get('hold_small',0)} | "
        f"🧯={symptoms.get('cb_trigger',0)} | "
        f"🧪={symptoms.get('discovery',0)}"
    )

    used_budget = (meta or {}).get("daily_budget", {})
    if used_budget:
        bu_lines = []
        for k in sorted(used_budget.keys()):
            bu_lines.append(f"{k}={fmt_num(used_budget[k])}")
        budget = "• <b>Budget hoje</b>: " + ", ".join(bu_lines)
    else:
        budget = "• <b>Budget hoje</b>: –"

    cooldown = "• <b>Cooldown</b>: ⏳ bloqueado nesta janela (sem bypass)." if cooldown_blocked else "• <b>Cooldown</b>: ok"
    streak_line = f"• <b>Streak</b>: bad={meta.get('bad_streak',0)}/{REQUIRED_BAD_STREAK} | good={meta.get('good_streak',0)}/{REQUIRED_GOOD_STREAK}"

    if proposed:
        ch_lines = []
        for k in sorted(proposed.keys()):
            ch_lines.append(f"— <code>{k}</code> → <code>{fmt_num(proposed[k])}</code>")
        ch_text = "\n".join(ch_lines)
        changes = f"<b>Overrides</b> ({'dry-run' if dry_run else 'aplicado'}):\n{ch_text}"
    else:
        changes = "<b>Overrides</b>: –"
        if discard_reasons:
            rs = []
            legend = {"at_limit":"limite", "no_budget":"sem budget", "no_diff":"sem diferença", "filtered":"filtrado"}
            for k in sorted(discard_reasons.keys()):
                rs.append(f"{k}: {legend.get(discard_reasons[k], discard_reasons[k])}")
            if rs:
                changes += "\n<i>Sem aplicar porque</i>:\n• " + "\n• ".join(rs)

    vdesc_line = f"\n<i>{vdesc}</i>" if vdesc else ""

    msg = (
        f"<b>{title}</b>{vdesc_line}\n"
        f"<code>{ts}</code>\n\n"
        f"{kp}\n"
        f"{sy}\n"
        f"{budget}\n"
        f"{cooldown}\n"
        f"{streak_line}\n\n"
        f"{changes}\n"
        f"• file: <code>{OVERRIDES}</code>\n"
    )
    return msg

# =========================
# MAIN
# =========================
def main(dry_run=False, verbose=True, force_telegram=False, no_telegram=False):
    now_local = datetime.datetime.now(LOCAL_TZ)
    print(now_local.strftime("%Y-%m-%d %H:%M:%S"))

    version_info = read_version_info(VERSIONS_FILE)

    kpis = get_7d_kpis()
    symptoms = read_symptoms_from_logs()

    cur = load_json(OVERRIDES, {}) or {}
    for k, v in DEFAULTS.items():
        cur.setdefault(k, v)

    meta = load_meta()

    # === garantir rollover diário do budget SEMPRE
    rollover_daily_budget_if_needed(meta)

    update_bad_streak(meta, kpis.get("profit_ppm_est", 0.0))
    update_good_streak(meta, kpis.get("profit_sat", 0), kpis.get("profit_ppm_est", 0.0))

    proposed = {}
    cooldown_blocked = False
    discard_reasons = {}

    if meta["bad_streak"] >= REQUIRED_BAD_STREAK:
        proposed = adjust(cur, kpis, symptoms)
        proposed = apply_limits(proposed)

        prof_sat = kpis.get("profit_sat", 0)
        profit_ppm_est = kpis.get("profit_ppm_est", 0)
        severe_bad = (prof_sat <= 0 or profit_ppm_est < PPM_WORSE)
        too_many_floorlocks = (symptoms.get("floor_lock", 0) >= 20)
        if proposed and severe_bad:
            for k in ("REBAL_FLOOR_MARGIN", "OUTRATE_FLOOR_FACTOR", "REVFLOOR_MIN_PPM_ABS"):
                meta.setdefault("daily_budget", {})
                meta["daily_budget"].pop(k, None)

        pre_budget = dict(proposed)
        proposed = enforce_daily_budget(cur, proposed, meta)

        if pre_budget and not proposed:
            discard_reasons = explain_discarded_changes(cur, pre_budget, proposed, meta)

        if verbose and proposed:
            used = meta.get("daily_budget", {})
            print("[budget] uso hoje:", used)

        bypass_cooldown = severe_bad and too_many_floorlocks
        if proposed and (not can_change_now(meta)) and (not bypass_cooldown):
            cooldown_blocked = True
            if verbose:
                print("KPIs 7d:", kpis)
                print("Symptoms:", symptoms)
                print("Changes (bloqueado por cooldown temporal):", proposed)
                print(f"[info] aguardando {MIN_HOURS_BETWEEN_CHANGES}h entre alterações.")
            if (force_telegram or (tg_enabled() and not no_telegram)):
                tg_msg = build_tg_message(version_info, now_local, kpis, symptoms, proposed, meta, dry_run, cooldown_blocked=True, discard_reasons=discard_reasons)
                tg_send(tg_msg)
            save_meta(meta)
            return
    else:
        if verbose:
            print("KPIs 7d:", kpis)
            print("Symptoms:", symptoms)
            print("Changes:", {})
            print(f"[info] tendência insuficiente (bad_streak={meta['bad_streak']}/{REQUIRED_BAD_STREAK}).")
        if (force_telegram or (tg_enabled() and not no_telegram)):
            tg_msg = build_tg_message(version_info, now_local, kpis, symptoms, {}, meta, dry_run, cooldown_blocked=False, discard_reasons=discard_reasons)
            tg_send(tg_msg)
        save_meta(meta)
        return

    if meta.get("good_streak", 0) >= REQUIRED_GOOD_STREAK:
        cu = float(cur.get("COOLDOWN_HOURS_UP", DEFAULTS["COOLDOWN_HOURS_UP"]))
        new_up = clamp(cu - 1, *LIMITS["COOLDOWN_HOURS_UP"])
        if "COOLDOWN_HOURS_UP" not in proposed and new_up != cu:
            proposed["COOLDOWN_HOURS_UP"] = new_up

        plmax = float(cur.get("PERSISTENT_LOW_MAX", DEFAULTS["PERSISTENT_LOW_MAX"]))
        new_plmax = clamp(plmax - 0.02, *LIMITS["PERSISTENT_LOW_MAX"])
        if "PERSISTENT_LOW_MAX" not in proposed and new_plmax != plmax:
            proposed["PERSISTENT_LOW_MAX"] = new_plmax

    if verbose:
        print("KPIs 7d:", kpis)
        print("Symptoms:", symptoms)
        print("Changes:", proposed if proposed else {})
        if not proposed and discard_reasons:
            print("[info] propostas descartadas:", discard_reasons)

    if (force_telegram or (tg_enabled() and not no_telegram)):
        tg_msg = build_tg_message(version_info, now_local, kpis, symptoms, proposed, meta, dry_run, cooldown_blocked=False, discard_reasons=discard_reasons)
        tg_send(tg_msg)

    if not dry_run and proposed:
        cur.update(proposed)
        save_json(OVERRIDES, cur)
        meta["last_change_ts"] = int(time.time())
        save_meta(meta)
        if verbose:
            print(f"[ok] overrides atualizados em {OVERRIDES}")
    elif dry_run and proposed and verbose:
        print("[dry-run] alterações propostas (não salvas).")
        save_meta(meta)
    else:
        if verbose:
            print("[info] nada a alterar.")
        save_meta(meta)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Apenas mostra os ajustes; não grava o JSON.")
    ap.add_argument("--telegram", action="store_true", help="Força envio no Telegram (mesmo em dry-run).")
    ap.add_argument("--no-telegram", action="store_true", help="Não envia mensagem no Telegram.")
    args = ap.parse_args()
    main(dry_run=args.dry_run, verbose=True, force_telegram=args.telegram, no_telegram=args.no_telegram)
