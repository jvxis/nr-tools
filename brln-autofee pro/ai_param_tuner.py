#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, sqlite3, datetime, time, math, argparse
from collections import defaultdict
from zoneinfo import ZoneInfo
import re
from pathlib import Path

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

# === paths (ajuste se necessário) ===
DB_PATH     = '/home/admin/lndg/data/db.sqlite3'
CACHE_PATH  = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH  = "/home/admin/.cache/auto_fee_state.json"
OVERRIDES   = "/home/admin/nr-tools/brln-autofee pro/autofee_overrides.json"

# log do autofee que MOSTRA o que foi aplicado
AUTOFEE_LOG_PATH = "/home/admin/autofee-apply.log"

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
    "REBAL_FLOOR_MARGIN":      (0.05, 0.30),   # ↑ teto 0.25 -> 0.30
    "REVFLOOR_MIN_PPM_ABS":    (100, 400),
    "OUTRATE_FLOOR_FACTOR":    (0.85, 1.35),   # ↑ teto 1.20 -> 1.35
    "BOS_PUSH_MIN_ABS_PPM":    (5, 20),
    "BOS_PUSH_MIN_REL_FRAC":   (0.01, 0.06),
    "COOLDOWN_HOURS_DOWN":     (3, 18),
    "COOLDOWN_HOURS_UP":       (1, 12),
    # Opcional (se usar blend de custo)
    "REBAL_BLEND_LAMBDA":      (0.0, 1.0),
    # Opcional: expor bump de margem negativa do Auto-fee
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
    # Opcional (se usar blend de custo)
    "REBAL_BLEND_LAMBDA": 0.30,
    # Opcional: caso seja lido pelo Auto-fee
    "NEG_MARGIN_SURGE_BUMP": 0.05,
}

# Anti-ratchet (higiene)
MIN_HOURS_BETWEEN_CHANGES = 6        # intervalo mínimo entre gravações de overrides
REQUIRED_BAD_STREAK = 2              # nº mínimo de janelas seguidas com profit_ppm_est < 0

# Orçamento diário de variação ABSOLUTA por chave (somatório de |passos| no dia).
DAILY_CHANGE_BUDGET = {
    # Preço/pisos
    "OUTRATE_FLOOR_FACTOR": 0.08,    # ↑ 0.06 -> 0.08
    "REVFLOOR_MIN_PPM_ABS": 40,      # ↑ 30 -> 40
    "REBAL_FLOOR_MARGIN":   0.08,    # ↑ 0.05 -> 0.08

    # Reatividade
    "STEP_CAP":             0.03,

    # Surge / drenagem
    "SURGE_K":              0.15,
    "SURGE_BUMP_MAX":       0.08,
    "PERSISTENT_LOW_BUMP":  0.02,
    "PERSISTENT_LOW_MAX":   0.06,

    # Ruído de updates (BOS)
    "BOS_PUSH_MIN_ABS_PPM": 6,
    "BOS_PUSH_MIN_REL_FRAC":0.01,

    # Histerese
    "COOLDOWN_HOURS_UP":    3,
    "COOLDOWN_HOURS_DOWN":  4,

    # (Opcional) mistura de custo — se usar “blend”
    "REBAL_BLEND_LAMBDA":   0.20,

    # Opcional: ajuste de bump de margem negativa
    "NEG_MARGIN_SURGE_BUMP": 0.03,
}
META_PATH = "/home/admin/nr-tools/brln-autofee pro/autofee_meta.json"


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

def get_7d_kpis():
    # KPIs derivados do LNDg: lucro, custo de rebal, etc.
    t2 = datetime.datetime.now(datetime.timezone.utc)
    t1 = t2 - datetime.timedelta(days=LOOKBACK_DAYS)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Forwards 7d
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

    # Rebal payments 7d
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
    """
    Lê o último bloco de relatório do autofee (texto aplicado) em /home/admin/autofee-apply.log e conta tags.
    Retorna um dict com: floor_lock, no_down_low, hold_small, cb_trigger, discovery.
    Também tenta parsear a linha 'Symptoms: {...}' se ela existir no relatório.
    """
    counts = {
        "floor_lock": 0,
        "no_down_low": 0,
        "hold_small": 0,
        "cb_trigger": 0,
        "discovery": 0,
    }

    log_path = Path(AUTOFEE_LOG_PATH)
    if not log_path.exists():
        return counts

    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            size = f.tell()
            back = min(size, 200_000)  # lê só o final pra ser leve
            f.seek(size - back)
            tail = f.read()
    except Exception:
        return counts

    # tenta isolar o último bloco do relatório
    header_re = re.compile(r'(?:DRY[-\s]*RUN\s*)?[\u2699\uFE0F\u200D\uFE0F]*\s*AutoFee\s*\|\s*janela\s*\d+d', re.IGNORECASE)
    hits = list(header_re.finditer(tail))
    block = tail[hits[-1].start():] if hits else tail

    # 1) Se houver "Symptoms: {...}" no bloco, parseia
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

    # 2) Contagem direta por TAGs (complementa o que já foi lido)
    counts["floor_lock"] += len(re.findall(r'🧱floor-lock', block))
    counts["no_down_low"] += len(re.findall(r'🙅‍♂️no-down-low', block))
    counts["hold_small"] += len(re.findall(r'🧘hold-small', block))
    counts["cb_trigger"] += len(re.findall(r'🧯\s*CB:', block))
    counts["discovery"]  += len(re.findall(r'🧪discovery', block))

    return counts

def adjust(overrides, kpis, symptoms):
    """
    Regras conservadoras de ajuste (pró-lucro).
    Retorna NOVOS VALORES (absolutos) apenas para chaves a alterar.
    """
    changed = {}

    prof_sat = kpis["profit_sat"]
    out_ppm  = kpis["out_ppm7d"]
    rebal_ppm= kpis["rebal_cost_ppm7d"]
    profit_ppm_est = kpis["profit_ppm_est"]

    # carrega atuais (ou defaults)
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
    # opcionais
    REBAL_BLEND_LAMBDA    = get("REBAL_BLEND_LAMBDA")
    NEG_MARGIN_SURGE_BUMP = get("NEG_MARGIN_SURGE_BUMP")

    # --- severidade (pró-lucro em sats) ---
    if prof_sat <= 0:
        bad_tier = "hard"  # prejuízo em sats → reagir forte
    elif prof_sat < SAT_PROFIT_MIN and profit_ppm_est < PPM_MEH:
        bad_tier = "medium"
    elif profit_ppm_est < PPM_WORSE:
        bad_tier = "medium"
    else:
        bad_tier = "ok"

    # --- sinais globais úteis ---
    rebal_overpriced = (rebal_ppm >= out_ppm) or ((out_ppm - rebal_ppm) < 50)

    # 1) P/L ruim e rebal caro → endurecer pisos (intensidade por bad_tier)
    if bad_tier in ("hard", "medium") and rebal_overpriced:
        incr = 1.0 if bad_tier == "hard" else 0.66
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR + 0.03*incr, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REVFLOOR_MIN_PPM_ABS = int(clamp(REVFLOOR_MIN_PPM_ABS + 10*incr, *LIMITS["REVFLOOR_MIN_PPM_ABS"]))
        REBAL_FLOOR_MARGIN   = clamp(REBAL_FLOOR_MARGIN + 0.02*incr, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REVFLOOR_MIN_PPM_ABS"] = REVFLOOR_MIN_PPM_ABS
        changed["REBAL_FLOOR_MARGIN"]   = REBAL_FLOOR_MARGIN

        # opcional: dar mais “pressão” a canais com margem negativa no Auto-fee
        NEG_MARGIN_SURGE_BUMP = clamp(NEG_MARGIN_SURGE_BUMP + (0.02 if bad_tier=="hard" else 0.01),
                                      *LIMITS["NEG_MARGIN_SURGE_BUMP"])
        changed["NEG_MARGIN_SURGE_BUMP"] = NEG_MARGIN_SURGE_BUMP

    # 2) MUITO floor-lock recorrente → só reduzir a margin SE não estivermos em tendência ruim
    if symptoms.get("floor_lock", 0) >= 15 and bad_tier == "ok":
        REBAL_FLOOR_MARGIN = clamp(REBAL_FLOOR_MARGIN - 0.02, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["REBAL_FLOOR_MARGIN"] = REBAL_FLOOR_MARGIN

    # 3) Drenagem crônica (no-down-low alto) → subir PERSISTENT_LOW_BUMP e SURGE_K
    if symptoms.get("no_down_low", 0) >= 10:
        PERSISTENT_LOW_BUMP = clamp(PERSISTENT_LOW_BUMP + 0.01, *LIMITS["PERSISTENT_LOW_BUMP"])
        SURGE_K = clamp(SURGE_K + 0.05, *LIMITS["SURGE_K"])
        SURGE_BUMP_MAX = clamp(SURGE_BUMP_MAX + 0.03, *LIMITS["SURGE_BUMP_MAX"])
        changed["PERSISTENT_LOW_BUMP"] = PERSISTENT_LOW_BUMP
        changed["SURGE_K"] = SURGE_K
        changed["SURGE_BUMP_MAX"] = SURGE_BUMP_MAX

    # 3b) Drenagem crônica + tendência ruim → permitir escalada um pouco maior (teto)
    if (symptoms.get("no_down_low", 0) >= 10) and (profit_ppm_est < 0):
        PERSISTENT_LOW_MAX = clamp(PERSISTENT_LOW_MAX + 0.02, *LIMITS["PERSISTENT_LOW_MAX"])
        changed["PERSISTENT_LOW_MAX"] = PERSISTENT_LOW_MAX

    # 4) Muitas micro-updates seguradas (hold-small) → relaxar thresholds do BOS (apenas se lucro > 0)
    if symptoms.get("hold_small", 0) >= 20 and prof_sat > 0:
        BOS_PUSH_MIN_ABS_PPM  = int(clamp(BOS_PUSH_MIN_ABS_PPM - 2, *LIMITS["BOS_PUSH_MIN_ABS_PPM"]))
        BOS_PUSH_MIN_REL_FRAC = clamp(BOS_PUSH_MIN_REL_FRAC - 0.005, *LIMITS["BOS_PUSH_MIN_REL_FRAC"])
        changed["BOS_PUSH_MIN_ABS_PPM"]  = BOS_PUSH_MIN_ABS_PPM
        changed["BOS_PUSH_MIN_REL_FRAC"] = BOS_PUSH_MIN_REL_FRAC

    # 5) Circuit-breaker demais → reduzir STEP_CAP e reforçar cooldown de queda
    if symptoms.get("cb_trigger", 0) >= 8:
        STEP_CAP = clamp(STEP_CAP - 0.01, *LIMITS["STEP_CAP"])
        COOLDOWN_DOWN = clamp(COOLDOWN_DOWN + 2, *LIMITS["COOLDOWN_HOURS_DOWN"])
        changed["STEP_CAP"] = STEP_CAP
        changed["COOLDOWN_HOURS_DOWN"] = COOLDOWN_DOWN
        COOLDOWN_UP = clamp(COOLDOWN_UP + 1, *LIMITS["COOLDOWN_HOURS_UP"])
        changed["COOLDOWN_HOURS_UP"] = COOLDOWN_UP

    # 6) Quando já estamos lucrando bem em sats e a margem ppm está perto do zero,
    #    afrouxa levemente pisos para buscar movimento SEM perder lucro.
    if (prof_sat >= SAT_PROFIT_MIN and profit_ppm_est > -40 and symptoms.get("floor_lock", 0) >= 25):
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR - 0.01, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REBAL_FLOOR_MARGIN   = clamp(REBAL_FLOOR_MARGIN - 0.01, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REBAL_FLOOR_MARGIN"]   = REBAL_FLOOR_MARGIN

    # Rollback suave condicionado a good_streak (feito no main, mas se quiser manter aqui, deixe neutro)
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
                meta.setdefault("good_streak", 0)   # <--- novo
                meta.setdefault("daily_budget", {})
                meta.setdefault("last_day", None)
                return meta
    except:
        pass
    # estrutura inicial
    return {"last_change_ts": 0, "bad_streak": 0, "good_streak": 0, "daily_budget": {}, "last_day": None}

def save_meta(meta):
    os.makedirs(os.path.dirname(META_PATH), exist_ok=True)
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)

def can_change_now(meta):
    now = int(time.time())
    hours = (now - int(meta.get("last_change_ts", 0))) / 3600.0
    return hours >= MIN_HOURS_BETWEEN_CHANGES

def update_bad_streak(meta, profit_ppm_est):
    # tendencia ruim quando profit_ppm_est < 0
    if profit_ppm_est < 0:
        meta["bad_streak"] = int(meta.get("bad_streak", 0)) + 1
    else:
        meta["bad_streak"] = 0

def update_good_streak(meta, prof_sat, profit_ppm_est):
    if profit_ppm_est > 0 and prof_sat >= SAT_PROFIT_MIN:
        meta["good_streak"] = int(meta.get("good_streak", 0)) + 1
    else:
        meta["good_streak"] = 0

def enforce_daily_budget(current_overrides, proposed_new_values, meta):
    """
    Limita variação ABSOLUTA aplicada por dia (soma de |passos|).
    Recebe valores absolutos propostos e devolve valores absolutos aprovados (pós-limite).
    """
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
            # para chaves não-numéricas, apenas permite
            allowed[k] = new_abs
            continue

        diff = new_abs - old_abs
        if diff == 0:
            continue

        limit = DAILY_CHANGE_BUDGET.get(k)
        if not limit:
            # sem orçamento → permite total, mas ainda respeita LIMITS
            allowed[k] = new_abs
            continue

        used = float(meta["daily_budget"].get(k, 0.0))
        room = max(0.0, limit - used)
        step = diff

        # Se não há espaço, pula
        if room <= 0:
            continue

        # Se o passo excede o espaço, corta
        if abs(step) > room:
            step = math.copysign(room, step)

        final_val = old_abs + step
        allowed[k] = final_val
        meta["daily_budget"][k] = used + abs(step)

    return allowed

def apply_limits(proposed):
    """Aplica LIMITS (clamp) nos valores numéricos propostos."""
    out = {}
    for k, v in proposed.items():
        if k in LIMITS:
            lo, hi = LIMITS[k]
            out[k] = clamp(float(v), lo, hi) if isinstance(v, (int, float)) else v
        else:
            out[k] = v
    return out

# =========================
# MAIN
# =========================
def main(dry_run=False, verbose=True):
    # imprime timestamp local no topo do bloco de logs
    print(datetime.datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"))
    kpis = get_7d_kpis()
    symptoms = read_symptoms_from_logs()

    # carrega overrides atuais (ou defaults como base)
    cur = load_json(OVERRIDES, {}) or {}
    for k, v in DEFAULTS.items():
        cur.setdefault(k, v)

    # anti-ratchet meta
    meta = load_meta()
    update_bad_streak(meta, kpis.get("profit_ppm_est", 0.0))
    update_good_streak(meta, kpis.get("profit_sat", 0), kpis.get("profit_ppm_est", 0.0))

    # cálculo de variações desejadas (absolutas)
    proposed = {}
    if meta["bad_streak"] >= REQUIRED_BAD_STREAK:
        proposed = adjust(cur, kpis, symptoms)
        # aplica limites de range
        proposed = apply_limits(proposed)

        # --- pista de emergência: libera budget dos pisos em cenário crítico ---
        prof_sat = kpis.get("profit_sat", 0)
        profit_ppm_est = kpis.get("profit_ppm_est", 0)
        # “hard” ruim se prejuízo em sats OU ppm muito ruim
        severe_bad = (prof_sat <= 0 or profit_ppm_est < PPM_WORSE)
        too_many_floorlocks = (symptoms.get("floor_lock", 0) >= 20)
        if proposed and severe_bad:
            # libera orçamento diário para as 3 chaves de piso
            for k in ("REBAL_FLOOR_MARGIN", "OUTRATE_FLOOR_FACTOR", "REVFLOOR_MIN_PPM_ABS"):
                meta.setdefault("daily_budget", {})
                meta["daily_budget"].pop(k, None)

        # aplica orçamento diário
        proposed = enforce_daily_budget(cur, proposed, meta)

        if verbose and proposed:
            used = load_json(META_PATH, {}).get("daily_budget", {})
            print("[budget] uso hoje:", used)

        # cooldown com bypass em cenário crítico + floorlock alto
        bypass_cooldown = severe_bad and too_many_floorlocks
        if proposed and (not can_change_now(meta)) and (not bypass_cooldown):
            if verbose:
                print("KPIs 7d:", kpis)
                print("Symptoms:", symptoms)
                print("Changes (bloqueado por cooldown temporal):", proposed)
                print(f"[info] aguardando {MIN_HOURS_BETWEEN_CHANGES}h entre alterações.")
            save_meta(meta)
            return
    else:
        if verbose:
            print("KPIs 7d:", kpis)
            print("Symptoms:", symptoms)
            print("Changes:", {})
            print(f"[info] tendência insuficiente (bad_streak={meta['bad_streak']}/{REQUIRED_BAD_STREAK}).")
        save_meta(meta)
        return

    # --- rollback suave (afrouxar lentamente) condicionado a good_streak ---
    if meta.get("good_streak", 0) >= REQUIRED_GOOD_STREAK:
        # Afrouxa levemente apenas se não houver proposta conflitante
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
        print("Changes:", proposed)

    if not dry_run and proposed:
        # aplica (merge) e salva overrides
        cur.update(proposed)
        save_json(OVERRIDES, cur)
        meta["last_change_ts"] = int(time.time())
        save_meta(meta)
        if verbose:
            print(f"[ok] overrides atualizados em {OVERRIDES}")
    elif dry_run and proposed and verbose:
        print("[dry-run] alterações propostas (não salvas).")
        save_meta(meta)  # ainda assim atualiza meta (streak/orçamento do dia)
    elif verbose:
        print("[info] nada a alterar.")
        save_meta(meta)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Apenas mostra os ajustes; não grava o JSON.")
    args = ap.parse_args()
    main(dry_run=args.dry_run, verbose=True)
