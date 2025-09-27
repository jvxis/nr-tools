# Manual Completo — AutoFee LND (Amboss/LNDg/BOS)

> Guia prático e direto para entender **todos os parâmetros** e **todas as tags** do seu script de auto-fees — com exemplos reais e dicas de tuning.

Este manual consolida:

1. **Como o script decide as taxas**;
2. **Todos os parâmetros** (com valores padrão e quando mexer);
3. **Todas as tags/emojis do relatório**;
4. **Exemplos de leitura**;
5. **Perfis de ajuste rápido**.

Para uma visão geral rápida do **pipeline** e leitura das **tags**, você também pode conferir os manuais anteriores, que inspiraram esta versão:  e .

---

## 1) O que o script faz (visão geral)

Ele ajusta automaticamente o **fee rate (ppm)** de cada canal **aberto** no seu LND para maximizar **lucro com estabilidade**. O alvo é calculado a partir de:

* **Sinal de mercado (seed Amboss p65 7d + guardas + EMA)**
* **Liquidez do canal (out_ratio)** e **persistência de drenagem**
* **Custo de rebalanço** (piso anti-prejuízo, global e/ou por canal)
* **Histórico de forwards** (out_ppm7d, fwd_count)
* **Boosts de demanda/receita** (surge/top revenue/margem negativa)
* **Ritmo controlado** (step cap dinâmico, cooldown, anti micro-update)
* **Segurança** (circuit breaker) e **sanidade** (clamps, floors, discovery)

Se o canal está **offline**, ele **não aplica** mudança (gera um *skip* detalhado) e registra status no cache. Um guia com a anatomia das linhas e ícones também está no manual legado de tags. 

---

## 2) Pipeline resumido

1. Snap do `lncli listchannels` (capacidade, saldos, pubkey, **active**).
2. Se **offline** ⇒ `⏭️🔌 skip` (mostra há quanto tempo e último **online**).
3. Carrega 7d do LNDg (forwards + payments de rebal).
4. Busca **seed** Amboss (série 7d) e aplica guardas + **EMA**.
5. Define **alvo base**: `seed + COLCHAO_PPM`.
6. Ajusta por **liquidez** e **persistência** de drenagem.
7. Aplica **boosts** (surge/top/neg margem) respeitando *step cap*.
8. Calcula **pisos** (rebal floor + outrate floor), com *cap* pelo **seed**.
9. **Step cap** (dinâmico), **cooldown** e **gate anti micro-update**.
10. **Circuit breaker** se fluxo caiu após subida.
11. Aplica via **BOS** (ou apenas imprime em *dry-run* / *excl-dry*).
    (Para detalhes dos campos de linha/ícones, ver manual de tags. )

---

## 3) Parâmetros — guia completo (com “quando mexer”)

> Dica: altere **poucos parâmetros por vez**, observe 2–3 dias e ajuste.

### 3.1. Caminhos, tokens e integrações

* `DB_PATH`: caminho do SQLite do LNDg.
* `LNCLI`: binário do `lncli`.
* `BOS`: caminho do `bos`.
* `AMBOSS_TOKEN` / `AMBOSS_URL`: credenciais da Amboss.
* `TELEGRAM_TOKEN` / `TELEGRAM_CHAT`: opcionais para envio automático do relatório.

### 3.2. Janelas, cache e estado

* `LOOKBACK_DAYS = 7`: janela usada para métricas.
* `CACHE_PATH`, `STATE_PATH`: arquivos JSON com cache e estado (seed anterior, baseline de fwds, status online/offline, etc.).

  * **Não editar manualmente**; são mantidos pelo script.

### 3.3. Limites base e colchão

* `BASE_FEE_MSAT = 0` (fees base fixas desativadas).
* `MIN_PPM = 100`, `MAX_PPM = 1500`: clamp final absoluto.
* `COLCHAO_PPM = 25`: “gordurinha” no alvo acima do seed.

  * **Aumente** se quiser **capturar mais valor**; **reduza** se quiser preço mais colado ao seed.

### 3.4. Política por liquidez (ajustes “leves”)

* `LOW_OUTBOUND_THRESH = 0.05` (<5% outbound = drenado ⇒ +1%)
* `HIGH_OUTBOUND_THRESH = 0.20` (>20% outbound ⇒ −1%)
* `LOW_OUTBOUND_BUMP = 0.01`, `HIGH_OUTBOUND_CUT = 0.01`
* `IDLE_EXTRA_CUT = 0.005` (queda extra quando ocioso com muita saída)

  * **Agressivo**: subir `LOW_OUTBOUND_BUMP` para 0.02–0.03.

### 3.5. Persistência de baixo outbound (streak)

* `PERSISTENT_LOW_ENABLE = True`
* `PERSISTENT_LOW_THRESH = 0.10` (define “baixo”)
* `PERSISTENT_LOW_STREAK_MIN = 3` (mínimo de rodadas seguidas)
* `PERSISTENT_LOW_BUMP = 0.05` (por rodada extra), `PERSISTENT_LOW_MAX = 0.20`
* `PERSISTENT_LOW_OVER_CURRENT_ENABLE = True`: se alvo ≤ taxa atual, escala **em cima da atual** (evita ficar travado).
* `PERSISTENT_LOW_MIN_STEP_PPM = 5`: passo mínimo nessa escalada.

  * **Quando mexer**: se canais drenados **não sobem** o suficiente, aumente `PERSISTENT_LOW_BUMP` (ex.: 0.07–0.10).

### 3.6. Peso do volume de **entrada** do peer (Amboss)

* `VOLUME_WEIGHT_ALPHA = 0.20`: peers que trazem muita **entrada** ficam com seed ponderado maior/menor vs média.

  * **Aumente** se quiser priorizar peers que te abastecem; **0** para desligar.

### 3.7. Circuit breaker

* `CB_WINDOW_DAYS = 7`, `CB_DROP_RATIO = 0.70`
* `CB_REDUCE_STEP = 0.10` (recuo de 10%)
* `CB_GRACE_DAYS = 7` (janela curta para reagir cedo)

  * Protege contra “subi e matei o fluxo”.

### 3.8. Pisos (anti-prejuízo)

**Rebal floor** (piso pelo custo de rebalanço):

* `REBAL_FLOOR_ENABLE = True`
* `REBAL_FLOOR_MARGIN = 0.15` (piso = custo*(1+15%))
* `REBAL_COST_MODE = "per_channel" | "global" | "blend"`
* `REBAL_BLEND_LAMBDA = 0.30` (para “blend”: 30% global + 70% canal)
* `REBAL_PERCHAN_MIN_VALUE_SAT = 200_000` (confiança mínima no custo por canal)
* `REBAL_FLOOR_SEED_CAP_FACTOR = 1.6` (floor **não** pode subir demais vs seed)

**Outrate floor** (piso por *out_ppm7d*):

* `OUTRATE_FLOOR_ENABLE = True`
* `OUTRATE_FLOOR_FACTOR = 1` (ou `0.95` com dinâmico)
* `OUTRATE_FLOOR_MIN_FWDS = 5` (amostra mínima)
* **Dinâmico**:

  * `OUTRATE_FLOOR_DYNAMIC_ENABLE = True`
  * `OUTRATE_FLOOR_DISABLE_BELOW_FWDS = 3` (desliga para amostra baixa)
  * `OUTRATE_FLOOR_FACTOR_LOW = 0.95` (piso um pouco menor entre 3–9 fwds)

> Dica: **se aparecer muito `🧱floor-lock`**, você está **“vendendo barato”** vs custo. Ou o custo está alto demais (rebal caro). Ajuste margem/disable dinâmico com cuidado. Referência de leitura de tags: 

### 3.9. Discovery (prospecção de preço)

* `DISCOVERY_ENABLE = True`
* `DISCOVERY_OUT_MIN = 0.30` (muita saída sobrando)
* `DISCOVERY_FWDS_MAX = 0` (sem forwards)
* Drops extras para ociosos duros:

  * `DISCOVERY_HARDDROP_DAYS_NO_BASE = 14`
  * `DISCOVERY_HARDDROP_CAP_FRAC = 0.20` (step cap de queda)
  * `DISCOVERY_HARDDROP_COLCHAO = 10` (colchão menor para acelerar descida)

### 3.10. Seed smoothing (EMA)

* `SEED_EMA_ALPHA = 0.20`: suaviza saltos do seed Amboss.

### 3.11. Lucro/Demanda — boosts

* **Surge** (drenagem forte):

  * `SURGE_ENABLE = True`
  * `SURGE_LOW_OUT_THRESH = 0.10`, `SURGE_K = 0.50`, `SURGE_BUMP_MAX = 0.20`
* **Top revenue** (peer com grande share da sua receita de saída):

  * `TOP_REVENUE_SURGE_ENABLE = True`
  * `TOP_OUTFEE_SHARE = 0.20`, `TOP_REVENUE_SURGE_BUMP = 0.12`
* **Margem 7d negativa**:

  * `NEG_MARGIN_SURGE_ENABLE = True`
  * `NEG_MARGIN_SURGE_BUMP = 0.08`, `NEG_MARGIN_MIN_FWDS = 5`

> Todas respeitam *step cap* se `SURGE_RESPECT_STEPCAP = True`.

### 3.12. Anti micro-update (BOS)

* `BOS_PUSH_MIN_ABS_PPM = 10`, `BOS_PUSH_MIN_REL_FRAC = 0.03`
  Evita “ruído” em mudanças pequenas (a não ser que o **floor** force).

### 3.13. Offline skip

* `OFFLINE_SKIP_ENABLE = True`
  Mantém cache de status por canal: **🟢on / 🔴off / 🟢back** (voltou).
  (Manual de leitura de status nas linhas: )

### 3.14. Cooldown / Histerese

* `APPLY_COOLDOWN_ENABLE = True`
* `COOLDOWN_HOURS_UP = 3`, `COOLDOWN_HOURS_DOWN = 6`
* `COOLDOWN_FWDS_MIN = 2` (pede algum tráfego entre mudanças)
* **Queda em rota lucrativa exige ainda mais cautela**:

  * `COOLDOWN_PROFIT_DOWN_ENABLE = True`
  * `COOLDOWN_PROFIT_MARGIN_MIN = 0` (margin>0)
  * `COOLDOWN_PROFIT_FWDS_MIN = 10` (e fwd_count≥10)

### 3.15. Sharding (opcional)

* `SHARDING_ENABLE = False`
* `SHARD_MOD = 3` ⇒ cada canal é tratado ~1/3 das rodadas.
  Mostra `⏭️🧩 ... skip (shard X/Y)` quando “fora do slot”. 

### 3.16. Normalização de **novo inbound** (peer abriu o canal)

* `NEW_INBOUND_NORMALIZE_ENABLE = True`
* Janela: `NEW_INBOUND_GRACE_HOURS = 48`
* Características do canal “novo inbound”:

  * `NEW_INBOUND_OUT_MAX = 0.05` (out ~0)
  * `NEW_INBOUND_REQUIRE_NO_FWDS = True` (sem forwards)
  * Só ativa se **taxa atual** for bem **acima do seed**:

    * `NEW_INBOUND_MIN_DIFF_FRAC = 0.25` e `NEW_INBOUND_MIN_DIFF_PPM = 50`
  * Step cap **maior para reduzir**: `NEW_INBOUND_DOWN_STEPCAP_FRAC = 0.15`
  * Tag: `NEW_INBOUND_TAG = "🌱new-inbound"`
  * Efeitos colaterais: desliga **surge**, ignora persistência de alta e **ignora cooldown para cair** (apenas nesse caso).

### 3.17. Classificação dinâmica (sink/source/router)

* `CLASSIFY_ENABLE = True`
* `CLASS_BIAS_EMA_ALPHA = 0.45` (EMA do viés in/out)
* Amostra mínima:

  * `CLASS_MIN_FWDS = 6`, `CLASS_MIN_VALUE_SAT = 60_000`
* Limiares:

  * **Sink**: `SINK_BIAS_MIN = 0.50` e `SINK_OUTRATIO_MAX = 0.15`
  * **Source**: `SOURCE_BIAS_MIN = 0.35` (via |bias|), `SOURCE_OUTRATIO_MIN = 0.58`
  * **Router**: `ROUTER_BIAS_MAX = 0.25` (|bias| pequeno com tráfego nos dois sentidos)
  * Histerese de decisão: `CLASS_CONF_HYSTERESIS = 0.10`
* Políticas por classe:

  * **Sink**: `SINK_EXTRA_FLOOR_MARGIN = 0.05`, `SINK_MIN_OVER_SEED_FRAC = 0.90` (não descer abaixo de 90% do seed)
  * **Source**: `SOURCE_SEED_TARGET_FRAC = 0.60` (prefere alvo mais baixo nas quedas), `SOURCE_DISABLE_OUTRATE_FLOOR = True`
  * **Router**: `ROUTER_STEP_CAP_BONUS = 0.02` (+2 pp de reatividade)
* Tags: `TAG_SINK = "🏷️sink"`, `TAG_SOURCE = "🏷️source"`, `TAG_ROUTER = "🏷️router"`, `TAG_UNKNOWN = "🏷️unknown"`

### 3.18. Modo “Extreme drain” (drenado crônico com demanda)

* `EXTREME_DRAIN_ENABLE = True`
* Ativa se: `low_streak ≥ EXTREME_DRAIN_STREAK (20)` **e** `out_ratio < 0.03` **e** `baseline_fwd7d>0`.
* Efeito: `EXTREME_DRAIN_STEP_CAP = 0.15` (step cap maior **para subir**) e `EXTREME_DRAIN_MIN_STEP_PPM = 15`.

### 3.19. Piso por tráfego em **super-rotas** (Revenue floor)

* `REVFLOOR_ENABLE = True`
* `REVFLOOR_BASELINE_THRESH = 150` (canal muito ativo)
* `REVFLOOR_MIN_PPM_ABS = 140` (e considera `seed*0.40`)
* Força um **mínimo** extra quando a rota roda muito.

### 3.20. Depuração e exclusões

* `DEBUG_TAGS = True` (exibe `🧬seedcap:none` e `🔍t{target}/r{raw}/f{floor}` no fim da linha)
* `EXCL_DRY_VERBOSE = True` (mostra **linha completa** para peers excluídos)

  * CLI: `--excl-dry-verbose` ou `--excl-dry-tag-only` (só imprime `🚷excl-dry`)
* `EXCLUSION_LIST = {...}`: pubkeys ignorados (apenas *dry-run* na saída).

---

## 4) Tags & Emojis — dicionário rápido

> A anatomia completa com exemplos ilustrados está no manual de tags anterior, que permanece 100% válido para leitura e interpretação (ícones de ação, `alvo`, `out_ratio`, `seed`, `floor`, `marg`, `rev_share`, etc.). 

**Principais:**

* **Ação**: `✅🔺` (subiu), `✅🔻` (desceu), `🫤⏸️` (manteve), `⏭️🔌` (skip offline), `⏭️🧩` (skip shard). 
* **Seed guards**: `🧬seedcap:p95`, `🧬seedcap:prev+X%`, `🧬seedcap:abs`, `🧬seedcap:none`. 
* **Liquidez**: `🙅‍♂️no-down-low` (bloqueia queda drenado), `🌱new-inbound`.
* **Ritmo e travas**: `⛔stepcap`, `⛔stepcap-lock`, `🧱floor-lock`, `🧘hold-small`, `⏳cooldown...`, `🧯 CB:`. 
* **Boosts**: `⚡surge+X%`, `👑top+...`, `💹negm+8%`. 
* **Classe**: `🏷️sink`, `🏷️source`, `🏷️router`, `🏷️unknown` + `🧭bias±0.xx` (debug).
* **Status**: `🟢on`, `🟢back`, `🔴off`. 
* **Exclusão**: `🚷excl-dry` (linha *dry* para peers excluídos). 
* **Debug final**: `🔍t{alvo}/r{raw_step}/f{floor}` (quando `DEBUG_TAGS=True`). 

---

## 5) Exemplos de leitura

### (A) Drenado + receita alta

```
✅🔺 speedupln.com: set 494→566 ppm (+14.6%) | alvo 570 | out_ratio 0.07 | out_ppm7d≈410 | seed≈480 | floor≥450 | marg≈-20 | rev_share≈0.22 | ⚡surge+18% 👑top+12% ⛔stepcap 🔍t570/r566/f450 🟢on
```

* Drenado (`out_ratio` baixo) + **top revenue** ⇒ alvo subiu com **boosts**; *step cap* limitou a subida desta rodada.

### (B) Sobrando saída + sem forwards (discovery)

```
🫤⏸️ PeerABC: mantém 300 ppm | alvo 285 | out_ratio 0.62 | out_ppm7d≈0 | seed≈260 | floor≥240 | rev_share≈0.00 | 🧪discovery ⛔stepcap 🔍t285/r285/f240 🟢on
```

* Discovery ativo (sem forwards) ⇒ *out-floor* desativado; *step cap* ainda pode segurar a queda.

### (C) Piso travando (floor-lock)

```
🫤⏸️ hqq: mantém 1100 ppm | alvo 900 | out_ratio 0.08 | out_ppm7d≈739 | seed≈665 | floor≥1065 | marg≈-535 | 🧱floor-lock 🔍t900/r900/f1065 🟢on
```

* Seu **piso** (custo + margem e/ou outrate) ficou **acima** do alvo: não dá para baixar hoje. Ajuste custos ou margens para destravar.

> Exemplos de anatomia de linha e interpretação também estão no manual de tags anterior. 

---

## 6) Dúvidas rápidas (FAQ)

* **Por que não aplicou a mudança?**
  Veja as tags: pode ser `⏳cooldown...`, `🧘hold-small`, `⛔stepcap-lock` ou `🧱floor-lock`.

* **Por que `🚷excl-dry` aparece?**
  O peer está na lista de exclusão. Você vê **o que seria feito**, mas nada é aplicado. É possível trocar entre **linha detalhada** e **apenas tag** com `--excl-dry-verbose` / `--excl-dry-tag-only`.

* **Como sei que está offline/voltou?**
  O relatório mostra `⏭️🔌 ... skip: canal offline`, e depois `🟢back` quando voltar. (Convenção de ícones explicada no manual de tags.) 

---

## 7) Perfis de tuning prontos

**(A) Agressivo em drenagem/lucro**

* `PERSISTENT_LOW_BUMP = 0.07–0.10`, `PERSISTENT_LOW_MAX = 0.30`
* `SURGE_K = 0.8`, `SURGE_BUMP_MAX = 0.45`
* `STEP_CAP_LOW_005 = 0.18`, `STEP_CAP_LOW_010 = 0.12`
* `TOP_REVENUE_SURGE_BUMP = 0.15`
* **Mantenha pisos ligados** para não vender abaixo do custo.

**(B) Conservador/estável**

* `PERSISTENT_LOW_BUMP = 0.04`
* `SURGE_K = 0.45`, `SURGE_BUMP_MAX = 0.25`
* `STEP_CAP = 0.04`, `STEP_CAP_LOW_005 = 0.08`
* `BOS_PUSH_MIN_ABS_PPM = 12` (menos updates)

**(C) Descoberta (encher canais ociosos)**

* `DISCOVERY_ENABLE = True` (como já está)
* `OUTRATE_FLOOR_DYNAMIC_ENABLE = True` (para desligar em amostra baixa)
* `STEP_CAP_IDLE_DOWN = 0.15` (desce mais rápido quando sem forwards)

---

## 8) Execução

CLI:

```bash
python3 brln-autofee-2.py           # executa “valendo”
python3 brln-autofee-2.py --dry-run # só simula (mantém classe se DRYRUN_SAVE_CLASS=True)
# Verbosidade dos excluídos:
python3 brln-autofee-2.py --excl-dry-verbose   # padrão (linha completa)
python3 brln-autofee-2.py --excl-dry-tag-only  # só “🚷excl-dry”
```

Cron (ex. 1×/hora):

```cron
0 * * * * /usr/bin/python3 /home/admin/lndtools/brln-autofee-2.py >> /home/admin/lndtools/autofee.log 2>&1
```

---



