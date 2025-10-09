# Manual Completo — AutoFee LND (Amboss/LNDg/BOS)

> Guia prático para entender **como o script decide as taxas**, **todos os parâmetros** (com *defaults do seu código*), **todas as tags**, exemplos e perfis de tuning.

* Base: Amboss **p65 7d** com **guards + EMA + seed híbrido (mediana/volatilidade/ratio)**; **liquidez/streak**, **pisos por rebal/out-rate/PEG**, **boosts**, **step cap dinâmico**, **cooldown/histerese**, **circuit breaker**, **discovery hard-drop**, **classificação sink/source/router** e **exclusões em dry**.

---

## 1) Visão geral (pipeline)

1. Snapshot `lncli listchannels` (capacidade, saldos, pubkey, `active`, `initiator`).
2. Se **offline** ⇒ `⏭️🔌 skip` (com tempo offline/último online).
3. Lê 7d do **LNDg**: forwards (out_ppm7d, contagens e valores) e pagamentos de **rebal** (global e por canal).
4. Busca **seed base** (Amboss série 7d `incoming_fee_rate_metrics / weighted_corrected_mean`) e aplica:

   * **Guards**: `p95-cap`, limite de salto vs seed anterior, teto absoluto.
   * **Seed híbrido**: blend com **mediana**, penalidade por **volatilidade (σ/μ)** e viés por **ratio out/in** (Amboss).
   * **Ponderação por ENTRADA** do peer (share vs média).
   * **EMA** no seed (suavização).
5. Alvo base: `seed + COLCHAO_PPM`.
6. Ajustes por **liquidez** (out_ratio), **persistência de baixo outbound** (streak) e **novo inbound** (queda facilitada).
7. **Boosts** (surge/top/neg-margin) → respeitam o *step cap*.
8. **Pisos**: rebal floor + outrate floor (cap por seed) + **🧲 PEG** (cola no preço que já vendeu).
9. **Step cap dinâmico**, **cooldown/histerese** (regras especiais p/ PEG e new-inbound) e **anti micro-update**.
10. **Circuit breaker** recua se fluxo cair após subida.
11. Aplica via **BOS** (ou simula em *dry* para excluídos).

---

## 2) Parâmetros — completo (com “quando mexer”)

### 2.1. Caminhos, binários, tokens

* `DB_PATH = '/home/admin/lndg/data/db.sqlite3'`
* `LNCLI = 'lncli'`
* `BOS = '/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/bos'`
* `AMBOSS_TOKEN` / `AMBOSS_URL = 'https://api.amboss.space/graphql'`
* `TELEGRAM_TOKEN` / `TELEGRAM_CHAT` (opcional: envia relatório)
* Versões: primeira linha de `VERSIONS_FILE` define a “versão ativa” exibida no relatório.

### 2.2. Janela, cache e overrides

* `LOOKBACK_DAYS = 7`
* `CACHE_PATH = '/home/admin/.cache/auto_fee_amboss.json'`
* `STATE_PATH = '/home/admin/.cache/auto_fee_state.json'`
* Overrides dinâmicos (sem editar o script):
  `OVERRIDES_PATH = '/home/admin/lndtools/autofee_overrides.json'`
  (apenas chaves já existentes são aplicadas)

### 2.3. Limites/base

* `MIN_PPM = 100` | `MAX_PPM = 2000` (clamp final)
* `COLCHAO_PPM = 25`
* (Há `BASE_FEE_MSAT = 0`, mas hoje não é usado; ver “Legados”)

**Quando mexer:** `MAX_PPM↑` permite a estratégia **PEG** acompanhar outrates altos.

### 2.4. Liquidez — “ajustes leves”

* `LOW_OUTBOUND_THRESH = 0.05` | `LOW_OUTBOUND_BUMP = 0.01`
* `HIGH_OUTBOUND_THRESH = 0.20` | `HIGH_OUTBOUND_CUT = 0.01`
* `IDLE_EXTRA_CUT = 0.005` (queda extra se ocioso e muita saída)

### 2.5. Persistência de baixo outbound (streak)

* `PERSISTENT_LOW_ENABLE = True`
* `PERSISTENT_LOW_THRESH = 0.10`
* `PERSISTENT_LOW_STREAK_MIN = 3`
* `PERSISTENT_LOW_BUMP = 0.05` por rodada (máx `PERSISTENT_LOW_MAX = 0.20`)
* **Over current**: `PERSISTENT_LOW_OVER_CURRENT_ENABLE = True` + `PERSISTENT_LOW_MIN_STEP_PPM = 5`
  (se o alvo ficar abaixo/igual ao atual, sobe “em cima do atual”)

### 2.6. Peso por **entrada** do peer (Amboss)

* `VOLUME_WEIGHT_ALPHA = 0.20` (banda ~±30%).
  **0** desliga.

### 2.7. Circuit breaker

* `CB_DROP_RATIO = 0.70`, `CB_REDUCE_STEP = 0.10`, `CB_GRACE_DAYS = 7`
  (nota: `CB_WINDOW_DAYS` existe, mas não é usado diretamente)

### 2.8. Pisos — Rebal / Outrate / PEG

**Rebal floor**

* `REBAL_FLOOR_ENABLE = True`
* `REBAL_FLOOR_MARGIN = 0.15`
* `REBAL_COST_MODE = 'per_channel' | 'global' | 'blend'`
* `REBAL_BLEND_LAMBDA = 0.20` (se “blend”: 20% global + 80% canal)
* `REBAL_PERCHAN_MIN_VALUE_SAT = 400_000` (só usa “por canal” com sinal ≥ 400k sat)
* Cap do piso por seed: `REBAL_FLOOR_SEED_CAP_FACTOR = 1.2`

**Outrate floor (out_ppm7d)**

* `OUTRATE_FLOOR_ENABLE = True`
* `OUTRATE_FLOOR_FACTOR = 1.10`
* `OUTRATE_FLOOR_MIN_FWDS = 4`
* Dinâmico:
  `OUTRATE_FLOOR_DYNAMIC_ENABLE = True`
  `OUTRATE_FLOOR_DISABLE_BELOW_FWDS = 5`
  `OUTRATE_FLOOR_FACTOR_LOW = 0.85`

**PEG (cola no preço que já vendeu)**

* `OUTRATE_PEG_ENABLE = True`
* `OUTRATE_PEG_MIN_FWDS = 5`
* `OUTRATE_PEG_HEADROOM = 0.01` (+1% sobre o outrate observado)
* Queda abaixo do PEG exige: `OUTRATE_PEG_GRACE_HOURS = 36`
* Demanda real “libera” teto seed-based: `OUTRATE_PEG_SEED_MULT = 1.10`

> Em **discovery** e quando `fwd_count==0`, pisos por outrate são desligados.

### 2.9. Step cap (ritmo)

* Base: `STEP_CAP = 0.05`
* Dinâmico: `DYNAMIC_STEP_CAP_ENABLE = True`

  * Muito baixo outbound:
    `STEP_CAP_LOW_005 = 0.10` (out_ratio < 0.03)
    `STEP_CAP_LOW_010 = 0.07` (0.03 ≤ out_ratio < 0.05)
  * Queda ocioso: `STEP_CAP_IDLE_DOWN = 0.12` (fwd=0 & out_ratio>0.60)
  * Passo mínimo: `STEP_MIN_STEP_PPM = 5`
* Bônus router: `ROUTER_STEP_CAP_BONUS = 0.02`

### 2.10. Discovery (prospecção)

* `DISCOVERY_ENABLE = True`
* `DISCOVERY_OUT_MIN = 0.40` | `DISCOVERY_FWDS_MAX = 0`
* Hard-drop (ocioso “duro”):

  * `DISCOVERY_HARDDROP_DAYS_NO_BASE = 6`
  * `DISCOVERY_HARDDROP_CAP_FRAC = 0.20`
  * `DISCOVERY_HARDDROP_COLCHAO = 10`
* Em discovery, **rebal-floor e outrate-floor** ficam **OFF** (fica só `MIN_PPM`).

### 2.11. Seed smoothing (EMA)

* `SEED_EMA_ALPHA = 0.20` (0 desliga)

### 2.12. **Seed híbrido (novo) — mediana/volatilidade/ratio**

* `SEED_ADJUST_ENABLE = True`
* Blend com mediana: `SEED_BLEND_MEDIAN_ALPHA = 0.30` (30% mediana + 70% seed base)
* Penalidade por volatilidade (σ/μ):
  `SEED_VOLATILITY_K = 0.25`, `SEED_VOLATILITY_CAP = 0.15`
* Viés por **ratio** = out_wcorr / in_wcorr:
  `SEED_RATIO_K = 0.20`, clamp do fator: `0.80..1.50`
* Cache Amboss genérica: `AMBOSS_CACHE_TTL_SEC = 10800` (3h)

### 2.13. Boosts (demanda/receita)

* **Surge**: `SURGE_ENABLE=True`, `SURGE_LOW_OUT_THRESH=0.10`, `SURGE_K=0.50`, `SURGE_BUMP_MAX=0.20`
* **Top revenue**: `TOP_REVENUE_SURGE_ENABLE=True`, `TOP_OUTFEE_SHARE=0.20`, `TOP_REVENUE_SURGE_BUMP=0.12`
* **Margem negativa**: `NEG_MARGIN_SURGE_ENABLE=True`, `NEG_MARGIN_SURGE_BUMP=0.05`, `NEG_MARGIN_MIN_FWDS=5`
* (Há `SURGE_RESPECT_STEPCAP=True`, mas o pipeline já respeita o cap de qualquer forma)

### 2.14. Revenue floor (super-rotas)

* `REVFLOOR_ENABLE = True`
* `REVFLOOR_BASELINE_THRESH = 80`
* `REVFLOOR_MIN_PPM_ABS = 140`

### 2.15. Anti micro-update

* `BOS_PUSH_MIN_ABS_PPM = 15` | `BOS_PUSH_MIN_REL_FRAC = 0.04`

### 2.16. Offline skip

* `OFFLINE_SKIP_ENABLE = True` (cache em `chan_status` + tags `🟢on/🟢back/🔴off`)

### 2.17. Cooldown / Histerese

* `APPLY_COOLDOWN_ENABLE = True`
* `COOLDOWN_HOURS_UP = 3` | `COOLDOWN_HOURS_DOWN = 5`
* `COOLDOWN_FWDS_MIN = 2`
* Quedas mais conservadoras quando lucrando:

  * `COOLDOWN_PROFIT_DOWN_ENABLE = True`
  * `COOLDOWN_PROFIT_MARGIN_MIN = 10`
  * `COOLDOWN_PROFIT_FWDS_MIN = 10`
* **Exceções**:
  Em **discovery** (queda), **new-inbound** (queda) e **queda abaixo do PEG** sem cumprir `OUTRATE_PEG_GRACE_HOURS` → tratadas à parte.

### 2.18. Sharding (opcional)

* `SHARDING_ENABLE = False` | `SHARD_MOD = 3`
  Fora do slot ⇒ `⏭️🧩 ... skip (shard X/Y)`.

### 2.19. Novo inbound (peer abriu o canal)

* `NEW_INBOUND_NORMALIZE_ENABLE = True`
* Janela: `NEW_INBOUND_GRACE_HOURS = 48`
* Condições: `NEW_INBOUND_OUT_MAX = 0.05`, `NEW_INBOUND_REQUIRE_NO_FWDS = True`
* Só ativa se taxa atual ≫ seed:
  `NEW_INBOUND_MIN_DIFF_FRAC = 0.25` **e** `NEW_INBOUND_MIN_DIFF_PPM = 50`
* Step cap **maior só para reduzir**: `NEW_INBOUND_DOWN_STEPCAP_FRAC = 0.15`
* Tag: `NEW_INBOUND_TAG = "🌱new-inbound"`

### 2.20. Classificação (sink/source/router)

* `CLASSIFY_ENABLE = True` | `CLASS_BIAS_EMA_ALPHA = 0.45`
* Amostra mínima: `CLASS_MIN_FWDS = 4`, `CLASS_MIN_VALUE_SAT = 40_000`
* Limiares:

  * Sink: `SINK_BIAS_MIN = 0.50`, `SINK_OUTRATIO_MAX = 0.15`
  * Source: `SOURCE_BIAS_MIN = 0.35`, `SOURCE_OUTRATIO_MIN = 0.58`
  * Router: `ROUTER_BIAS_MAX = 0.30`
  * Histerese: `CLASS_CONF_HYSTERESIS = 0.10`
* Políticas:

  * Sink: `SINK_EXTRA_FLOOR_MARGIN = 0.10`, `SINK_MIN_OVER_SEED_FRAC = 1.00`
  * Source: `SOURCE_SEED_TARGET_FRAC = 0.60`, `SOURCE_DISABLE_OUTRATE_FLOOR = True`
  * Router: `ROUTER_STEP_CAP_BONUS = 0.02`

### 2.21. Extreme drain (drenado crônico **com demanda**)

* `EXTREME_DRAIN_ENABLE = True`
* Ativa se: `low_streak ≥ 20`, `out_ratio < 0.03` **e** `baseline_fwd7d > 0`
* Efeito (subidas): `EXTREME_DRAIN_STEP_CAP = 0.15`, `EXTREME_DRAIN_MIN_STEP_PPM = 15`

### 2.22. Debug / exclusões

* `DEBUG_TAGS = True` (exibe `🧬seedcap:*`, `🔍t/r/f`, etc.)
* Excluídos em DRY:

  * `EXCLUSION_LIST = {...}` → linha com `🚷excl-dry`
  * `EXCL_DRY_VERBOSE = True` (ou `--excl-dry-tag-only`)

---

## 3) Teto local condicional e clamp final

* Teto “suave” por canal: `local_max = min(MAX_PPM, max(800, int(seed * 1.8)))`
* **Exceção de demanda**: se drenado (`out_ratio < 0.10`) **ou** `out_ppm7d ≥ seed * OUTRATE_PEG_SEED_MULT`, autoriza teto via **outrate** (com `OUTRATE_PEG_HEADROOM`).
* Clamp final: `final = max(MIN_PPM, min(local_max, int(round(final_ppm))))`.

> Se o PEG “bate no teto”, **aumente `MAX_PPM`** para deixar o preço seguir.

---

## 4) Dicionário de tags

**Travas/ritmo**

* `🧱floor-lock`, `⛔stepcap`, `⛔stepcap-lock`, `🧘hold-small`, `⏳cooldown...`

**Demanda/receita**

* `⚡surge+X%`, `👑top+X%`, `💹negm+X%`, `⚠️subprice`

**PEG/out-rate**

* `🧲peg` (piso colado no outrate; para cair abaixo precisa `OUTRATE_PEG_GRACE_HOURS`)

**Liquidez**

* `🙅‍♂️no-down-low`, `🌱new-inbound`, `🧪discovery`

**Seed/guards**

* `🧬seedcap:p95|prev+|abs|none` + ajustes híbridos `🔬med-blend`, `🔬volσ/μ-..%`, `🔬ratio×..`

**Classe**

* `🏷️sink/source/router/unknown`, `🧭bias±`, `🧭<classe>:<conf>`

**Segurança/estado**

* `🧯 CB:...`, `🟢on|🟢back|🔴off`, `⏭️🔌 skip`, `🚷excl-dry`, `🩹min-fix`

**Debug**

* `🔍t{alvo}/r{raw}/f{floor}`

---

## 5) Exemplos rápidos

**(A) PEG travando a queda**

```
🫤⏸️ PeerX: mantém 1500 ppm | alvo 605 | out_ratio 0.12 | out_ppm7d≈1624 | seed≈580 | floor≥1500 | 🧲peg 🧱floor-lock 🔍t605/r1745/f1500
```

— O outrate observável virou piso (PEG), logo a queda parou em **1500**.
👉 Quer seguir mais? **suba `MAX_PPM`**.

**(B) Drenado crônico sem baseline (stale-drain)**

```
🫤⏸️ PeerY: mantém 1107 ppm | alvo 1348 | out_ratio 0.01 | out_ppm7d≈0 | seed≈615 | 💤stale-drain ⛔stepcap 🔍t1348/r1217/f618
```

— Alto streak, sem forwards: subida limitada por stepcap.

**(C) Novo inbound — queda facilitada**

```
✅🔻 PeerZ: set 1200→980 ppm | 🌱new-inbound 🔍t940/r980/f560
```

— Em **new-inbound** a queda ignora o cooldown.

---

## 6) Perfis de tuning

**A) Agressivo pró-lucro/demanda**

* `PERSISTENT_LOW_BUMP=0.07–0.10`, `PERSISTENT_LOW_MAX=0.30`
* `SURGE_K=0.8`, `SURGE_BUMP_MAX=0.30–0.45`
* `STEP_CAP_LOW_005=0.15–0.18`, `STEP_CAP_LOW_010=0.10–0.12`
* `TOP_REVENUE_SURGE_BUMP=0.15`
* `MAX_PPM` ↑ para deixar o **PEG** acompanhar picos

**B) Conservador/estável**

* `PERSISTENT_LOW_BUMP=0.04`, `STEP_CAP=0.04`, `STEP_CAP_LOW_005=0.08`
* `SURGE_K=0.45`, `SURGE_BUMP_MAX=0.25`
* `BOS_PUSH_MIN_ABS_PPM=18` (menos updates)

**C) Descoberta (ociosos)**

* Já habilitado `DISCOVERY_ENABLE=True`
* `OUTRATE_FLOOR_DISABLE_BELOW_FWDS=5` (liga outrate floor só com sinal)
* `STEP_CAP_IDLE_DOWN=0.15` (acelera quedas onde sobra liquidez)

---

## 7) Execução

```bash
python3 brln-autofee-pro.py                # executa “valendo”
python3 brln-autofee-pro.py --dry-run      # só simula (classe ainda persiste)
# Excluídos:
python3 brln-autofee-pro.py --excl-dry-verbose   # (default) linha completa
python3 brln-autofee-pro.py --excl-dry-tag-only  # só “🚷excl-dry”
```

Cron (a cada hora):

```cron
0 * * * * /usr/bin/python3 /home/admin/nr-tools/brln-autofee pro/brln-autofee-pro.py >> /home/admin/autofee-apply.log 2>&1
```






