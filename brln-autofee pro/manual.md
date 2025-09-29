# Manual Completo — AutoFee LND (Amboss/LNDg/BOS)

> Guia prático para entender **como o script decide as taxas**, **todos os parâmetros** (com *defaults reais do seu código*), **todas as tags**, exemplos e perfis de tuning.

* Código base: versão com **Amboss p65 7d + guards + EMA**, **liquidez/streak**, **pisos por rebal/out-rate/PEG**, **boosts de demanda**, **step cap dinâmico**, **cooldown/histerese**, **circuit breaker**, **discovery hard-drop**, **classificação sink/source/router** e **exclusões em dry**.

---

## 1) Visão geral (pipeline)

1. `lncli listchannels` (capacidade, saldos, pubkey, `active`, `initiator`).
2. Se **offline** ⇒ `⏭️🔌 skip` (com tempo offline/último online).
3. Carrega 7d do **LNDg**: forwards (out_ppm7d, contagens e valores) e payments de **rebal**.
4. Busca **seed** (Amboss série 7d, submétrica `weighted_corrected_mean`), aplica **guards** (p95, salto máx, teto abs) + **EMA** + ponderação por **entrada** do peer.
5. Alvo base: `seed + COLCHAO_PPM`.
6. Ajustes por **liquidez** (out_ratio), **persistência de baixo outbound** e **novos inbound**.
7. **Boosts** (surge/top/neg-margin) → respeitam *step cap*.
8. **Pisos**: rebal floor + outrate floor (cap por seed) + **🧲PEG** de outrate (cola no preço que já vendeu).
9. **Step cap dinâmico**, **cooldown/histerese** (com regra especial para PEG e new-inbound) e **anti micro-update**.
10. **Circuit breaker** recua se fluxo cair após subida.
11. Aplica com **BOS** (ou simula em *dry* para excluídos).

---

## 2) Parâmetros — completo (com “quando mexer”)

### 2.1. Caminhos, binários, tokens

* `DB_PATH = '/home/admin/lndg/data/db.sqlite3'`
* `LNCLI = 'lncli'`
* `BOS = '/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/bos'`
* `AMBOSS_TOKEN` / `AMBOSS_URL = 'https://api.amboss.space/graphql'`
* `TELEGRAM_TOKEN` / `TELEGRAM_CHAT` (opcional: envio do relatório)

### 2.2. Janela, cache e estado

* `LOOKBACK_DAYS = 7`
* `CACHE_PATH = '/home/admin/.cache/auto_fee_amboss.json'`
* `STATE_PATH = '/home/admin/.cache/auto_fee_state.json'`
* **Overrides dinâmicos**: lê JSON opcional e sobrescreve chaves existentes

  * `OVERRIDES_PATH = '/home/admin/lndtools/autofee_overrides.json'`
  * Útil para experimentar *sem* editar o script.

### 2.3. Limites e base

* `BASE_FEE_MSAT = 0`
* `MIN_PPM = 100` | `MAX_PPM = 1500` (clamp final)
* `COLCHAO_PPM = 25` (gordura sobre o seed)

> **Quando mexer:** `COLCHAO_PPM↑` captura mais valor; `MAX_PPM↑` deixa o **PEG** seguir outrates altos (ver seção PEG).

### 2.4. Liquidez — “ajustes leves”

* `LOW_OUTBOUND_THRESH = 0.05` | `LOW_OUTBOUND_BUMP = 0.01`
* `HIGH_OUTBOUND_THRESH = 0.20` | `HIGH_OUTBOUND_CUT = 0.01`
* `IDLE_EXTRA_CUT = 0.005` (queda extra ocioso com muita saída)

> **Mais agressivo:** aumentar `LOW_OUTBOUND_BUMP` (0.02–0.03).

### 2.5. Persistência de baixo outbound (streak)

* `PERSISTENT_LOW_ENABLE = True`
* `PERSISTENT_LOW_THRESH = 0.10`
* `PERSISTENT_LOW_STREAK_MIN = 3`
* `PERSISTENT_LOW_BUMP = 0.05` por rodada (máx `PERSISTENT_LOW_MAX = 0.20`)
* **Over current**: `PERSISTENT_LOW_OVER_CURRENT_ENABLE = True` (+ `PERSISTENT_LOW_MIN_STEP_PPM = 5`)

> Se drenados **não sobem**: `PERSISTENT_LOW_BUMP↑` (0.07–0.10).

### 2.6. Ponderação por **entrada** do peer (Amboss)

* `VOLUME_WEIGHT_ALPHA = 0.20` (±30% de banda)

> **0** para desligar. Aumente se quer priorizar quem te abastece.

### 2.7. Circuit breaker (CB)

* `CB_WINDOW_DAYS = 7` (usa baseline 7d salvo)
* `CB_DROP_RATIO = 0.70` (fluxo caiu <70% do baseline?)
* `CB_REDUCE_STEP = 0.10` (recuo de 10%)
* `CB_GRACE_DAYS = 7`

### 2.8. Pisos (anti-prejuízo) — Rebal / Outrate / PEG

**Rebal floor**

* `REBAL_FLOOR_ENABLE = True`
* `REBAL_FLOOR_MARGIN = 0.10`
* `REBAL_COST_MODE = 'per_channel' | 'global' | 'blend'`
* `REBAL_BLEND_LAMBDA = 0.30` (se “blend”: 30% global + 70% canal)
* `REBAL_PERCHAN_MIN_VALUE_SAT = 400_000` (precisa sinal ≥ 400k sat)
* **Cap por seed**: `REBAL_FLOOR_SEED_CAP_FACTOR = 1.4`

**Outrate floor (por out_ppm7d)**

* `OUTRATE_FLOOR_ENABLE = True`
* `OUTRATE_FLOOR_FACTOR = 1`
* `OUTRATE_FLOOR_MIN_FWDS = 5`
* Dinâmico:

  * `OUTRATE_FLOOR_DYNAMIC_ENABLE = True`
  * `OUTRATE_FLOOR_DISABLE_BELOW_FWDS = 5`
  * `OUTRATE_FLOOR_FACTOR_LOW = 0.90`

**PEG do outrate (cola no “preço que já vendeu”)**

* `OUTRATE_PEG_ENABLE = True`
* `OUTRATE_PEG_MIN_FWDS = 1` (basta 1 forward para reconhecer preço)
* `OUTRATE_PEG_HEADROOM = 0.03` (folga de +3%)
* **Grace** para quedas abaixo do PEG: `OUTRATE_PEG_GRACE_HOURS = 72`
* Demanda real permite furar teto seed-based: `OUTRATE_PEG_SEED_MULT = 1.20`

> **Importante:** o PEG vira **piso** adicional. Se o outrate observado implicar `floor_ppm > MAX_PPM`, o **clamp final** segura em `MAX_PPM`. Para “seguir” outrates mais altos, **aumente `MAX_PPM`** (ou remova *clamp* intermediário e mantenha só o final).

### 2.9. Step cap (ritmo)

* Estático: `STEP_CAP = 0.05` (±5%)
* Dinâmico: `DYNAMIC_STEP_CAP_ENABLE = True`

  * Drenado extremo: `STEP_CAP_LOW_005 = 0.10` (out_ratio<0.03)
  * Baixo: `STEP_CAP_LOW_010 = 0.07` (0.03–0.05)
  * Queda ocioso: `STEP_CAP_IDLE_DOWN = 0.10` (fwd=0 & out_ratio>0.60)
  * Passos mínimos: `STEP_MIN_STEP_PPM = 5` (subida: ver *Extreme drain*)
* Bônus router: `ROUTER_STEP_CAP_BONUS = 0.02`

### 2.10. Discovery (prospecção)

* `DISCOVERY_ENABLE = True`
* `DISCOVERY_OUT_MIN = 0.30` | `DISCOVERY_FWDS_MAX = 0`
* **Hard-drop** (ocioso “duro”):

  * `DISCOVERY_HARDDROP_DAYS_NO_BASE = 10`
  * `DISCOVERY_HARDDROP_CAP_FRAC = 0.20` (queda mais rápida)
  * `DISCOVERY_HARDDROP_COLCHAO = 10` (colchão menor)
* Em discovery, **out-floor e rebal-floor** são desativados (só `MIN_PPM`).

### 2.11. Seed smoothing (EMA)

* `SEED_EMA_ALPHA = 0.20` (0 desliga)

### 2.12. Boosts (demanda/receita)

* **Surge**: `SURGE_ENABLE=True`, `SURGE_LOW_OUT_THRESH=0.10`, `SURGE_K=0.50`, `SURGE_BUMP_MAX=0.20`
* **Top revenue**: `TOP_REVENUE_SURGE_ENABLE=True`, `TOP_OUTFEE_SHARE=0.20`, `TOP_REVENUE_SURGE_BUMP=0.12`
* **Margem negativa**: `NEG_MARGIN_SURGE_ENABLE=True`, `NEG_MARGIN_SURGE_BUMP=0.05`, `NEG_MARGIN_MIN_FWDS=5`
* Respeitam cap: `SURGE_RESPECT_STEPCAP = True`

### 2.13. Revenue floor (super-rotas)

* `REVFLOOR_ENABLE = True`
* `REVFLOOR_BASELINE_THRESH = 150`
* `REVFLOOR_MIN_PPM_ABS = 140`
* Tag `⚠️subprice` aparece quando final < piso por tráfego.

### 2.14. Anti micro-update

* `BOS_PUSH_MIN_ABS_PPM = 15` | `BOS_PUSH_MIN_REL_FRAC = 0.04`

### 2.15. Offline skip

* `OFFLINE_SKIP_ENABLE = True` (cache: `chan_status`)
  Mostra `🟢on / 🟢back / 🔴off` e faz *skip* quando offline.

### 2.16. Cooldown / Histerese

* `APPLY_COOLDOWN_ENABLE = True`
* `COOLDOWN_HOURS_UP = 3` | `COOLDOWN_HOURS_DOWN = 6`
* `COOLDOWN_FWDS_MIN = 2`
* Quedas **mais conservadoras** quando lucrando:

  * `COOLDOWN_PROFIT_DOWN_ENABLE = True`
  * `COOLDOWN_PROFIT_MARGIN_MIN = 0`
  * `COOLDOWN_PROFIT_FWDS_MIN = 10`
* **Exceções importantes**:

  * Em **discovery** e **queda** ⇒ ignora cooldown.
  * Em **new-inbound** e **queda** ⇒ ignora cooldown.
  * Com **PEG**: queda abaixo do PEG só após `OUTRATE_PEG_GRACE_HOURS`.

### 2.17. Sharding (opcional)

* `SHARDING_ENABLE = False` | `SHARD_MOD = 3`
  Fora do slot ⇒ `⏭️🧩 ... skip (shard X/Y)`.

### 2.18. Novo inbound (peer abriu o canal)

* `NEW_INBOUND_NORMALIZE_ENABLE = True`
* Janela: `NEW_INBOUND_GRACE_HOURS = 48`
* Condições: `NEW_INBOUND_OUT_MAX = 0.05`, `NEW_INBOUND_REQUIRE_NO_FWDS = True`
* Só ativa se **taxa atual ≫ seed**:

  * `NEW_INBOUND_MIN_DIFF_FRAC = 0.25` **e** `NEW_INBOUND_MIN_DIFF_PPM = 50`
* Step cap **maior só para reduzir**: `NEW_INBOUND_DOWN_STEPCAP_FRAC = 0.15`
* Tag: `NEW_INBOUND_TAG = "🌱new-inbound"`

### 2.19. Classificação dinâmica (sink/source/router)

* `CLASSIFY_ENABLE = True` | `CLASS_BIAS_EMA_ALPHA = 0.45`
* Amostra mínima: `CLASS_MIN_FWDS = 4`, `CLASS_MIN_VALUE_SAT = 40_000`
* Limiares:

  * Sink: `SINK_BIAS_MIN = 0.50`, `SINK_OUTRATIO_MAX = 0.15`
  * Source: `SOURCE_BIAS_MIN = 0.35`, `SOURCE_OUTRATIO_MIN = 0.58`
  * Router: `ROUTER_BIAS_MAX = 0.30`
  * Histerese: `CLASS_CONF_HYSTERESIS = 0.10`
* Políticas:

  * Sink: `SINK_EXTRA_FLOOR_MARGIN = 0.05`, `SINK_MIN_OVER_SEED_FRAC = 0.90`
  * Source: `SOURCE_SEED_TARGET_FRAC = 0.60`, `SOURCE_DISABLE_OUTRATE_FLOOR = True`
  * Router: `ROUTER_STEP_CAP_BONUS = 0.02`

### 2.20. Extreme drain (drenado crônico **com demanda**)

* `EXTREME_DRAIN_ENABLE = True`
* Ativa se: `low_streak ≥ EXTREME_DRAIN_STREAK (20)` **e** `out_ratio < 0.03` **e** `baseline_fwd7d > 0`
* Efeito (subidas): `EXTREME_DRAIN_STEP_CAP = 0.15`, `EXTREME_DRAIN_MIN_STEP_PPM = 15`

### 2.21. Debug / exclusões / flags

* `DEBUG_TAGS = True` (exibe `🧬seedcap:*` e `🔍t/r/f`)
* Excluídos:

  * `EXCLUSION_LIST = {...}` (linha **DRY** com `🚷excl-dry`)
  * `EXCL_DRY_VERBOSE = True` (ou `--excl-dry-tag-only` para compactar)

---

## 3) Teto local condicional e clamp final

Além de `MAX_PPM`, há um **teto local** ancorado no seed:

* `local_max = min(MAX_PPM, max(800, int(seed * 1.8)))`
* **Exceção de demanda**: se drenado (out_ratio<low) **ou** outrate ≥ `seed * OUTRATE_PEG_SEED_MULT` ⇒ autoriza teto via outrate (com headroom do PEG).
* Clamp final: `final = max(MIN_PPM, min(local_max, final_ppm))`.

> Se você vê **outrate alto** e o PEG está “batendo no teto”, **suba `MAX_PPM`**.

---

## 4) Dicionário de tags (resumo)

* **Travas/ritmo**: `🧱floor-lock`, `⛔stepcap`, `⛔stepcap-lock`, `🧘hold-small`, `⏳cooldown...`
* **Demanda/receita**: `⚡surge+X%`, `👑top+X%`, `💹negm+X%`, `⚠️subprice`
* **PEG/out-rate**: `🧲peg` (cola no preço observado; quedas exigem `OUTRATE_PEG_GRACE_HOURS`)
* **Liquidez**: `🙅‍♂️no-down-low`, `🌱new-inbound`, `🧪discovery`
* **Seed guards**: `🧬seedcap:p95|prev+|abs|none`
* **Classe**: `🏷️sink/source/router/unknown`, `🧭bias±`, `🧭sink:conf`
* **Segurança**: `🧯 CB:`
* **Status**: `🟢on|🟢back|🔴off`, `⏭️🔌 skip`
* **Exclusões**: `🚷excl-dry`
* **Sanidade**: `🩹min-fix` (subiu para ≥ `MIN_PPM`)
* **Debug**: `🔍t{alvo}/r{raw}/f{floor}`


---

## 5) Exemplos de leitura rápidos

**(A) Piso travando com PEG ativo**

```
🫤⏸️ PeerX: mantém 1500 ppm | alvo 605 | out_ratio 0.12 | out_ppm7d≈1624 | seed≈580 | floor≥1500 | 👀 🧲peg 🧱floor-lock 🔍t605/r1745/f1500
```

— O PEG (outrate≈1 624) + clamp final pararam a queda em **1500**.
✅ Se quiser seguir outrate maior, **aumente `MAX_PPM`**.

**(B) Drenado crônico sem baseline (stale-drain)**

```
🫤⏸️ PeerY: mantém 1107 ppm | alvo 1348 | out_ratio 0.01 | out_ppm7d≈0 | seed≈615 | 💤stale-drain ⛔stepcap 🔍t1348/r1217/f618
```

— Alto streak, sem forwards recentes ⇒ melhor relaxar agressividade de subida.

**(C) New inbound “pesado” (queda facilitada)**

```
✅🔻 PeerZ: set 1200→980 ppm | 🌱new-inbound ⏳cooldown ignorado (queda) 🔍t940/r980/f560
```

— Em **new-inbound** a queda não espera cooldown.

---

## 6) Perfis de tuning

**A) Agressivo pró-lucro/demanda**

* `PERSISTENT_LOW_BUMP=0.07–0.10`, `PERSISTENT_LOW_MAX=0.30`
* `SURGE_K=0.8`, `SURGE_BUMP_MAX=0.45`
* `STEP_CAP_LOW_005=0.18`, `STEP_CAP_LOW_010=0.12`
* `TOP_REVENUE_SURGE_BUMP=0.15`
* `MAX_PPM` ↑ se quiser que o **PEG** acompanhe outrates altos.

**B) Conservador/estável**

* `PERSISTENT_LOW_BUMP=0.04`, `STEP_CAP=0.04`, `STEP_CAP_LOW_005=0.08`
* `SURGE_K=0.45`, `SURGE_BUMP_MAX=0.25`
* `BOS_PUSH_MIN_ABS_PPM=18` (menos updates)

**C) Descoberta (ociosos)**

* `DISCOVERY_ENABLE=True` (já está)
* `OUTRATE_FLOOR_DYNAMIC_ENABLE=True` e `OUTRATE_FLOOR_DISABLE_BELOW_FWDS=5`
* `STEP_CAP_IDLE_DOWN=0.15`

---

## 7) Execução (CLI/cron)

```bash
python3 brln-autofee-pro.py                # executa “valendo”
python3 brln-autofee-pro.py --dry-run      # só simula (classe ainda persiste)
# Excluídos:
python3 brln-autofee-pro.py --excl-dry-verbose   # (default) linha completa
python3 brln-autofee-pro.py --excl-dry-tag-only  # só “🚷excl-dry”
```

Cron (ex.: a cada hora):

```cron
0 * * * * /usr/bin/python3 /home/admin/nr-tools/brln-autofee pro/brln-autofee-pro.py >> /home/admin/autofee.log 2>&1
```






