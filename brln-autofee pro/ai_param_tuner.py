#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, sqlite3, datetime, time, math, argparse
from collections import defaultdict

# === paths (ajuste se necessário) ===
DB_PATH     = '/home/admin/lndg/data/db.sqlite3'
CACHE_PATH  = "/home/admin/.cache/auto_fee_amboss.json"
STATE_PATH  = "/home/admin/.cache/auto_fee_state.json"
OVERRIDES   = "autofee_overrides.json"

LOOKBACK_DAYS = 7

# === limites de segurança para knobs ===
LIMITS = {
    "STEP_CAP":                (0.02, 0.15),
    "SURGE_K":                 (0.20, 0.90),
    "SURGE_BUMP_MAX":          (0.10, 0.50),
    "PERSISTENT_LOW_BUMP":     (0.03, 0.12),
    "PERSISTENT_LOW_MAX":      (0.10, 0.40),
    "REBAL_FLOOR_MARGIN":      (0.05, 0.25),
    "REVFLOOR_MIN_PPM_ABS":    (100, 400),
    "OUTRATE_FLOOR_FACTOR":    (0.85, 1.20),
    "BOS_PUSH_MIN_ABS_PPM":    (5, 20),
    "BOS_PUSH_MIN_REL_FRAC":   (0.01, 0.06),
    "COOLDOWN_HOURS_DOWN":     (3, 18),
    "COOLDOWN_HOURS_UP":       (1, 12)
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
    "COOLDOWN_HOURS_UP": 3
}

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
    Lê STATE/CACHE e procura contadores de sintomas que seu reporter costuma indicar.
    Se quiser, você pode também varrer o último relatório impresso em arquivo e contar ocorrências.
    """
    cache = load_json(CACHE_PATH, {}) or {}
    state = load_json(STATE_PATH, {}) or {}

    # Heurística: se você salva o último relatório textual em /home/admin/lndtools/autofee.log,
    # vale a pena varrer as últimas N linhas e contar tags. Aqui mantemos simples:
    counts = {
        "floor_lock": 0,
        "no_down_low": 0,
        "hold_small": 0,
        "cb_trigger": 0
    }

    # Procura indicadores agregados no STATE (se você quiser, salve também contadores lá)
    # Mantemos zero se não existir — o agente continua robusto.
    return counts

def adjust(overrides, kpis, symptoms):
    """
    Regras conservadoras de ajuste.
    """
    changed = {}

    prof_sat = kpis["profit_sat"]
    out_ppm  = kpis["out_ppm7d"]
    rebal_ppm= kpis["rebal_cost_ppm7d"]

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

    # 1) Se lucro muito baixo ou negativo e rebal custo alto → endurecer pisos por receita
    if prof_sat < 0 or (rebal_ppm > 250 and (out_ppm - rebal_ppm) < 80):
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR + 0.03, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REVFLOOR_MIN_PPM_ABS = int(clamp(REVFLOOR_MIN_PPM_ABS + 10, *LIMITS["REVFLOOR_MIN_PPM_ABS"]))
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REVFLOOR_MIN_PPM_ABS"] = REVFLOOR_MIN_PPM_ABS

    # 2) Se MUITO floor-lock recorrente (supõe sintomas coletados) → reduzir REBAL_FLOOR_MARGIN
    if symptoms.get("floor_lock", 0) >= 15:
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

    # 4) Muitas micro-updates seguradas (hold-small) → relaxar thresholds do BOS
    if symptoms.get("hold_small", 0) >= 20 and prof_sat > 0:
        BOS_PUSH_MIN_ABS_PPM  = int(clamp(BOS_PUSH_MIN_ABS_PPM - 2, *LIMITS["BOS_PUSH_MIN_ABS_PPM"]))
        BOS_PUSH_MIN_REL_FRAC = clamp(BOS_PUSH_MIN_REL_FRAC - 0.005, *LIMITS["BOS_PUSH_MIN_REL_FRAC"])
        changed["BOS_PUSH_MIN_ABS_PPM"]  = BOS_PUSH_MIN_ABS_PPM
        changed["BOS_PUSH_MIN_REL_FRAC"] = BOS_PUSH_MIN_REL_FRAC

    # 5) Circuit-breaker disparando demais → desacelerar STEP_CAP e reforçar cooldown de queda
    if symptoms.get("cb_trigger", 0) >= 8:
        STEP_CAP = clamp(STEP_CAP - 0.01, *LIMITS["STEP_CAP"])
        COOLDOWN_DOWN = clamp(COOLDOWN_DOWN + 2, *LIMITS["COOLDOWN_HOURS_DOWN"])
        changed["STEP_CAP"] = STEP_CAP
        changed["COOLDOWN_HOURS_DOWN"] = COOLDOWN_DOWN

    # 6) Se lucro alto e rebal baixo → pode afrouxar levemente pisos para ganhar volume
    if prof_sat > 50_000 and rebal_ppm < 120 and out_ppm < 600:
        OUTRATE_FLOOR_FACTOR = clamp(OUTRATE_FLOOR_FACTOR - 0.02, *LIMITS["OUTRATE_FLOOR_FACTOR"])
        REBAL_FLOOR_MARGIN   = clamp(REBAL_FLOOR_MARGIN - 0.01, *LIMITS["REBAL_FLOOR_MARGIN"])
        changed["OUTRATE_FLOOR_FACTOR"] = OUTRATE_FLOOR_FACTOR
        changed["REBAL_FLOOR_MARGIN"]   = REBAL_FLOOR_MARGIN

    # retorna overrides novos (somente o que mudou)
    return changed

def main(dry_run=False, verbose=True):
    kpis = get_7d_kpis()
    symptoms = read_symptoms_from_logs()

    # carrega overrides atuais (ou defaults)
    cur = load_json(OVERRIDES, {}) or {}
    for k, v in DEFAULTS.items():
        cur.setdefault(k, v)

    delta = adjust(cur, kpis, symptoms)

    if verbose:
        print("KPIs 7d:", kpis)
        print("Symptoms:", symptoms)
        print("Changes:", delta)

    if not dry_run and delta:
        cur.update(delta)
        save_json(OVERRIDES, cur)
        if verbose:
            print(f"[ok] overrides atualizados em {OVERRIDES}")
    elif verbose:
        print("[info] nada a alterar.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Apenas mostra os ajustes; não grava o JSON.")
    args = ap.parse_args()
    main(dry_run=args.dry_run, verbose=True)
