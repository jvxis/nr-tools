# Manual do AutoFee LND — versão “Amboss + Lucro + Offline Skip”

Olá! 🎉 Este manual explica **o que o script faz**, **como ele decide cada taxa (ppm)** e **como ajustar os parâmetros** para priorizar **lucratividade** de acordo com seu perfil. Também trago **exemplos práticos**, dicas de **tuning**, como **interpretar o relatório** (emojis e tags), e um guia de **instalação/execução**.

> **Contexto:** você roda o script **a cada 1 hora**. Ótimo! Ele foi pensado para operar com essa cadência.

---

## Sumário

1. [O que o script faz](#o-que-o-script-faz)
2. [Fluxo de decisão (pipeline)](#fluxo-de-decisão-pipeline)
3. [Fontes de dados](#fontes-de-dados)
4. [Métricas importantes](#métricas-importantes)
5. [Parâmetros e como ajustar](#parâmetros-e-como-ajustar)
6. [Relatório: como ler as linhas, tags e emojis](#relatório-como-ler-as-linhas-tags-e-emojis)
7. [Exemplos práticos de decisão](#exemplos-práticos-de-decisão)
8. [Instalação, execução e cron](#instalação-execução-e-cron)
9. [Boas práticas de segurança](#boas-práticas-de-segurança)
10. [Dúvidas comuns (FAQ)](#dúvidas-comuns-faq)
11. [Perfis de tuning sugeridos](#perfis-de-tuning-sugeridos)

---

## O que o script faz

Ele **ajusta automaticamente as taxas de encaminhamento (fee rate em ppm)** dos seus canais LND para **maximizar lucro**, respeitando:

* **Demanda de mercado** (seed Amboss + surge pricing para canais drenados),
* **Seu custo de rebalanço** (piso que evita vender roteamento com prejuízo),
* **Histórico dos seus forwards**,
* **Liquidez dos canais** (outbound baixo/sobrando),
* **Segurança operacional** (circuit breaker, step caps, micro-update gate),
* **Disponibilidade** (🔥 **skip automático se o canal estiver offline**).

> Se o canal está **offline**, ele **não tenta** mudar a taxa. Em vez disso, **loga o skip** com emoji e **memoriza o status** (online/offline) no **cache**.

---

## Fluxo de decisão (pipeline)

**Por canal aberto**:

1. **Snapshot LND (`lncli listchannels`)**

   * Capacidade, saldos local/remote, pubkey do peer, **`active`** (online/offline).

2. **Se offline ⇒ skip cedo**

   * Loga: `⏭️🔌 ... skip: canal offline`, com **🟢on / 🔴off** e **🟢back** quando voltar.

3. **Dados 7d do LNDg (SQLite)**

   * Forwards de saída: volume, fees e **`out_ppm_7d`** + **`fwd_count`**.
   * Rebalances (globais e por canal) ⇒ **custo em ppm**.

4. **Sinal de mercado (Amboss)**

   * Série 7d de **incoming\_fee\_rate\_metrics / weighted\_corrected\_mean** do peer ⇒ **seed**.
   * **Guardas**: cap no P95, cap vs seed anterior, teto absoluto, e **EMA** para suavizar.

5. **Alvo inicial**

   * `target = seed + COLCHAO_PPM`.

6. **Ajustes por demanda & liquidez**

   * Persistência de outbound **baixo** (streak) ⇒ **bump**.
   * Liquidez (muito drenado/sobrando) ⇒ up/down leve.
   * **Surge pricing** se muito drenado.
   * **Top revenue** (peer que rende muito) ⇒ boost.
   * **Margem negativa** (você roteou abaixo do custo) ⇒ empurra pra cima.

7. **Step Cap dinâmico**

   * Limita a variação por rodada (evita “oscilação louca”).

8. **Discovery mode**

   * Se **sobrando liquidez** e **sem forwards**, acelera queda para “testar o mercado”.

9. **Circuit Breaker**

   * Se subiu e o tráfego caiu demais, recua um pouco.

10. **Pisos (garantias)**

    * **Rebal floor**: não cair abaixo do **custo de rebal** (global/canal) com margem.
    * **Outrate floor**: não cair abaixo de uma fração do seu **out\_ppm\_7d**.
    * Cap do piso pelo **seed** (evita piso “absurdo”).

11. **Gate anti-micro-update**

    * Evita mandar para o BOS ajustes mínimos que não valem a pena.

12. **Aplicação (BOS)**

    * Se mudou o suficiente, aciona `bos fees --to ... --set-fee-rate`.
    * Atualiza `STATE` (last\_ppm, baseline\_fwd7d, streak, last\_seed…).
    * Log bonitão com **tags** e **emojis**.
    * Se **dry-run**, apenas simula e imprime/Telegram.

---

## Fontes de dados

* **LND (lncli)**: snapshot dos canais + **`active`** (online/offline).
* **LNDg (SQLite)**:

  * `gui_forwards` (forwards de 7d)
  * `gui_payments` (rebalances de 7d)
* **Amboss GraphQL**: série 7d **incoming fee rate** do peer (seed).
* **STATE/CACHE JSON**: memória leve (streak, last\_ppm, status online/offline, seeds etc.).

---

## Métricas importantes

* **ppm (parts-per-million)**: `fee / amount * 1_000_000`.
* **out\_ratio**: `local_balance / capacity`.

  * **< 10%** ⇒ drenado (demanda alta por saída).
  * **> 20%** ⇒ sobrando saída (pode baixar um pouco).
* **out\_ppm\_7d**: ppm médio dos forwards de saída nos últimos 7 dias.
* **fwd\_count**: número de forwards saindo pelo canal nos últimos 7 dias.
* **seed (Amboss)**: preço “disposto a pagar” do mercado de entrada desse peer (p65 7d, com guardas/EMA).
* **rebal\_cost\_ppm**: custo de rebalanço (global/canal) nos seus pagamentos 7d.
* **floor (piso)**: menor ppm aceitável para **não operar no prejuízo** (derivado do custo).
* **baseline\_fwd7d** (STATE): base móvel do seu volume de forwards para o **circuit breaker**.

---

## Parâmetros e como ajustar

> **Dica:** comece com os **defaults**. Ajuste **poucos parâmetros de cada vez** e observe o relatório por alguns dias.

### 1) Caminhos e integrações

* `DB_PATH` — caminho do SQLite do LNDg.
* `LNCLI` — binário do lncli (ex.: `lncli`).
* `BOS` — caminho do BOS (ex.: `~/.npm-global/.../bos`).
* `AMBOSS_TOKEN`/`AMBOSS_URL` — acesso Amboss (use **token válido**).
* `TELEGRAM_TOKEN`/`TELEGRAM_CHAT` — opcionais para enviar relatório.

### 2) Limites e colchão

* `MIN_PPM` / `MAX_PPM` — limites duros (ex.: **100–1500**).
* `COLCHAO_PPM` — soma ao seed de mercado (ex.: **25 ppm**) para “pegar” valor acima do consenso.

### 3) Step cap (velocidade de mudança)

* `STEP_CAP` (ex.: **0.05** = 5% por rodada).
* **Dinâmico**:

  * `STEP_CAP_LOW_005` / `STEP_CAP_LOW_010` — acelera subida em drenagem (ex.: **0.12/0.08**).
  * `STEP_CAP_IDLE_DOWN` — acelera **queda** em discovery (ex.: **0.12**).
  * `STEP_MIN_STEP_PPM` — passo mínimo (ex.: **5 ppm**).

**Quando mexer:**
Se suas taxas demoram para reagir ⇒ aumente levemente os caps.
Se estão “nervosas” ⇒ reduza.

### 4) Política por liquidez

* `LOW_OUTBOUND_THRESH` (**0.05**) / `HIGH_OUTBOUND_THRESH` (**0.20**)
* `LOW_OUTBOUND_BUMP` (**+1%**) / `HIGH_OUTBOUND_CUT` (**-1%**)
* `IDLE_EXTRA_CUT` (**-0.5%**) para canais ociosos com muita saída.

**Agressivo:** subir `LOW_OUTBOUND_BUMP` para **0.02–0.03**.
**Conservador:** manter defaults.

### 5) Persistência de baixo outbound

* `PERSISTENT_LOW_ENABLE = True`
* `PERSISTENT_LOW_THRESH = 0.10` (baixo)
* `PERSISTENT_LOW_STREAK_MIN = 3` (3 rodadas seguidas)
* `PERSISTENT_LOW_BUMP = 0.05` por rodada extra, até `PERSISTENT_LOW_MAX = 0.20`
* `PERSISTENT_LOW_OVER_CURRENT_ENABLE = True` (empurra acima do atual)
* `PERSISTENT_LOW_MIN_STEP_PPM = 5`

**Quando mexer:** se seus canais drenados não sobem “o bastante”, aumente `PERSISTENT_LOW_BUMP` para **0.07–0.10**.

### 6) Peso do volume de entrada do peer (Amboss)

* `VOLUME_WEIGHT_ALPHA = 0.10` ⇒ peers que te trazem muita **entrada** ficam com seed levemente maior.

**Aumente** se quiser favorecer “hub de entrada” desses peers (ex.: **0.15**).
**Zere** se quiser ignorar isso.

### 7) Circuit Breaker

* `CB_DROP_RATIO = 0.60` — se, após subir taxa, o **fwd\_count** cair abaixo de 60% do **baseline**, aplica recuo.
* `CB_REDUCE_STEP = 0.10` — tamanho do recuo (10%).
* `CB_GRACE_DAYS = 10` — janela de carência.

### 8) Pisos (anti-prejuízo)

* **Rebal floor**:

  * `REBAL_FLOOR_ENABLE = True`
  * `REBAL_COST_MODE` = `"per_channel"` | `"global"` | `"blend"`
  * `REBAL_FLOOR_MARGIN = 0.15` (15% acima do custo)
  * `REBAL_PERCHAN_MIN_VALUE_SAT = 200_000` (volume mínimo para confiar no custo por canal)
  * `REBAL_FLOOR_SEED_CAP_FACTOR = 1.6` (piso não pode explodir muito acima do seed)

* **Outrate floor** (protege contra “dump” abaixo do que você já provou vender):

  * `OUTRATE_FLOOR_ENABLE = True`
  * `OUTRATE_FLOOR_FACTOR = 0.95` (95% do seu out\_ppm\_7d)
  * **Dinâmico:** desliga se `fwd_count < 5` e usa **0.80** entre 5 e 9.

### 9) Descoberta de preço (Discovery)

* `DISCOVERY_ENABLE = True`, `DISCOVERY_OUT_MIN = 0.30`, `DISCOVERY_FWDS_MAX = 0`.
  Se **tem muita saída disponível** e **zero forwards**, **acelera a queda** (para achar o preço que roda).

### 10) Seed smoothing (EMA)

* `SEED_EMA_ALPHA = 0.20` — suaviza seed do Amboss para evitar “pulos”.

### 11) Lucro/Demanda (boosts)

* **Surge Pricing** (muito drenado):

  * `SURGE_ENABLE = True`, `SURGE_LOW_OUT_THRESH = 0.08`, `SURGE_K = 0.60`, `SURGE_BUMP_MAX = 0.35`.

* **Top revenue** (peer responde por ≥ 20% das suas fees 7d):

  * `TOP_REVENUE_SURGE_ENABLE = True`, `TOP_OUTFEE_SHARE = 0.20`, `TOP_REVENUE_SURGE_BUMP = 0.10`.

* **Margem 7d negativa** (vendeu abaixo do custo com amostra suficiente):

  * `NEG_MARGIN_SURGE_ENABLE = True`, `NEG_MARGIN_SURGE_BUMP = 0.08`, `NEG_MARGIN_MIN_FWDS = 5`.

### 12) Anti micro-update (BOS)

* `BOS_PUSH_MIN_ABS_PPM = 3` e `BOS_PUSH_MIN_REL_FRAC = 0.01`
  Evita “ruído” e rate-limiting no BOS. *Obs.: se o **piso** exigir subir, o push é feito mesmo assim.*

### 13) Skip se canal estiver offline

* `OFFLINE_SKIP_ENABLE = True` (padrão ligado)
* Status armazenado em `CACHE_PATH` → chave `"chan_status"`
* Emojis: **🟢on**, **🔴off**, **🟢back** (voltou).
* Linha de log “skip offline” mostra **tempo offline** e **last\_on** aproximado.

> **Extra opcional**: se quiser ignorar flaps curtinhos, podemos adicionar um `OFFLINE_GRACE_SECONDS` (ex.: 180s). Basta pedir e eu te envio a pequena alteração.

---

## Relatório: como ler as linhas, tags e emojis

**Cabeçalho**

```
⚙️ AutoFee | janela 7d | rebal≈ 210 ppm (gui_payments)
📊 up 12 | down 5 | flat 30 | low_out 9 | offline 2
```

* **up/down/flat**: quantos canais subiram, desceram ou mantiveram.
* **low\_out**: drenados (<10%).
* **offline**: quantos foram skip.

**Linhas por canal (exemplos curto):**

* `✅🔺` / `✅🔻` — taxa aplicada (subiu/baixou)
* `🫤⏸️` — manteve (sem push, ou micro-update segurado `🧘hold-small`)
* `⏭️🔌` — **skip offline**
* **Tags**:

  * `🧬seedcap:p95` / `prev+50%` / `abs` — guardas do seed Amboss
  * `⛔stepcap` / `⛔stepcap-lock` — limite de passo atuou
  * `🧱floor-lock` — piso travou o alvo (não dá para baixar)
  * `🧪discovery` — modo descoberta
  * `⚡surge+X%` / `👑top+10%` / `💹negm+8%` — boosts de demanda/lucro
  * `🟢on` / `🟢back` / `🔴off` — status online/offline

---

## Exemplos práticos de decisão

### A) Canal drenado e rendendo bem

* `out_ratio = 0.04` (baixo), `fwd_count` alto, `rev_share = 0.25` (top revenue), seed ≈ 220 ppm.
* `target_base = 220 + 25 = 245`.
* Persistência (streak) ativa ⇒ +10% ⇒ \~270.
* Liquidez baixa ⇒ +1% ⇒ \~273.
* **Surge** (muito drenado) ⇒ +20% ⇒ \~328.
* Step cap dinâmico limita a subida por rodada.
* Piso rebal calcula minimo.
* Final ajusta para `max(stepcap, piso)`.

**Resultado**: sobe com força **em etapas** para capturar disposição a pagar, sem “socos” gigantes.

### B) Canal com muita saída e zero forwards

* `out_ratio = 0.65`, `fwd_count = 0`.
* Liquidez sobrando ⇒ -1% e `IDLE_EXTRA_CUT` (queda extra mínima).
* **Discovery** ativa ⇒ step cap de queda mais solto.
* **Outrate floor** desativado (para poder testar preço baixo).
* Piso rebal continua protegendo contra prejuízo.

**Resultado**: vai **descendo** até encontrar ppm que começa a rodar.

### C) Canal com margem negativa

* Você roteou, mas **`out_ppm_7d < custo_rebal`** ⇒ **`margem_ppm_7d < 0`**.
* Com amostra mínima (`fwd_count >= 5`), ativa **💹negm+8%** sobre o alvo.

**Resultado**: **empurra para cima** para recuperar margem.

---


## Dúvidas comuns (FAQ)

**1) Por que apareceu `🧱floor-lock`?**
O **piso** (custo de rebal/Outrate) ficou **acima** do alvo — o script impede cair abaixo para não operar com prejuízo. Para baixar, reduza custos de rebal ou ajuste `REBAL_FLOOR_MARGIN`/`OUTRATE_FLOOR_*`.

**2) O log diz `🧘hold-small`. O que é?**
O delta era **pequeno demais** (abaixo de `BOS_PUSH_MIN_*`) e **não forçado** pelo piso. Evita “micro-updates” no BOS.

**3) Vejo `⛔stepcap` com frequência. Normal?**
Sim. O Step Cap evita saltos grandes de preço por rodada. Se quiser reagir mais rápido, aumente `STEP_CAP` e os caps dinâmicos.

**4) `⏭️🔌 skip: canal offline` — mas o peer ficou online logo depois!**
Ótimo. Na próxima rodada, virá `🟢on` e possivelmente `🟢back`. Se flaps curtos estiverem te atrapalhando, vale adicionar um **grace** (ex.: ignorar offline < 180s).

**5) “Nada mudou em vários canais.”**
Pode ser **floor-lock**, **stepcap-lock** ou **hold-small**. Verifique as tags ao final da linha e ajuste conforme objetivo.

---

## Perfis de tuning sugeridos

### A) **Agressivo em drenagem / lucro**

* `PERSISTENT_LOW_BUMP = 0.07–0.10`, `PERSISTENT_LOW_MAX = 0.30`
* `SURGE_K = 0.8`, `SURGE_BUMP_MAX = 0.45`
* `STEP_CAP_LOW_005 = 0.18`, `STEP_CAP_LOW_010 = 0.12`
* `TOP_REVENUE_SURGE_BUMP = 0.15`
* Mantenha pisos **ligados** para não vender abaixo do custo.

### B) **Conservador / estável**

* `PERSISTENT_LOW_BUMP = 0.04`
* `SURGE_K = 0.45`, `SURGE_BUMP_MAX = 0.25`
* `STEP_CAP = 0.04`, `STEP_CAP_LOW_005 = 0.08`
* `BOS_PUSH_MIN_ABS_PPM = 5` (menos updates)

### C) **Descoberta de preço (encher fluxo em ociosos)**

* `DISCOVERY_ENABLE = True` (já está)
* Deixe `OUTRATE_FLOOR_DYNAMIC_ENABLE` (para desligar floor com `fwd_count < 5`)
* `STEP_CAP_IDLE_DOWN = 0.15` (desce mais rápido quando sem forwards)

---

## Conclusão

Com esse conjunto de **sinais** (mercado Amboss), **custos** (rebal/forwards), **liquidez**, **circuit breaker** e **proteções**, o script busca **equilibrar volume e margem**, privilegiando **lucratividade sustentável**.
O novo **skip de canais offline** evita “tiros no escuro” e deixa o relatório mais claro (com **🟢on / 🔴off / 🟢back**).

Se quiser, posso te enviar um **patch opcional** com `OFFLINE_GRACE_SECONDS` e/ou um modo de **carregar tokens por variáveis de ambiente** — é só falar como prefere 😉
