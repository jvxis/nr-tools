# Manual dos parâmetros

Antes de tudo, dois conceitos rápidos:

* **PPM (parts per million)**: é “por milhão”. Ex.: 500 ppm = 0,000500 = 0,05% de fee proporcional.
* **out\_ratio**: fração da capacidade do canal que está do **seu lado** (local\_balance / capacity).
  Ex.: 0,30 = 30% dos sats estão do seu lado (liquidez “saindo” disponível).

A cada execução, o script calcula um **alvo de fee** usando métricas (Amboss, custo de rebal, liquidez…), depois limita o tamanho do ajuste, aplica um piso de segurança, e **só então** define a nova fee.

---

## Limites base

### `BASE_FEE_MSAT = 0`

* **O que é:** base fee fixa por HTLC, em milisats.
* **No script atual:** está definido, mas **não é aplicado** ao chamar o `bos` (apenas a fee proporcional em ppm é ajustada).
* **Quando mexer:** normalmente deixe em `0`. Se um dia quiser usar base fee, será preciso estender a função que chama o `bos` para também ajustar a base.

### `MIN_PPM = 150`

* **O que é:** **piso mínimo** de fee proporcional (protege receita).
* **Efeito prático:** nunca deixa a fee cair abaixo disso — mesmo se o alvo sugerir menos.
* **Aumentar quando:** você quer evitar operar quase de graça.
* **Diminuir quando:** você quer competir agressivamente por volume em canais específicos.

### `MAX_PPM = 2500`

* **O que é:** **teto máximo** de fee proporcional.
* **Efeito prático:** impede que ajustes “fujam da curva”.
* **Aumentar quando:** canais muito premium ou rotas caras.
* **Diminuir quando:** você quer forçar teto baixo para ser competitivo.

---

## “Velocidade” de mudança por execução

### `STEP_CAP = 0.05`

* **O que é:** **limite de variação por execução**, em fração. `0.05 = 5%`.
* **Efeito prático:** se o alvo está muito distante da fee atual, você **anda só 5%** por rodada (suaviza oscilações).
* **Dica:** quanto **mais frequente** for seu cron (ex.: a cada 15–30 min), **menor** pode ser o `STEP_CAP` (3–5%). Se rodar raramente (ex.: 1×/dia), 10–20% faz mais sentido.

---

## Colchão fixo

### `COLCHAO_PPM = 30`

* **O que é:** um **extra fixo** somado ao alvo, para cobrir pequenas ineficiências/custos invisíveis.
* **Aumentar quando:** você percebe que “no fio da navalha” ainda há prejuízo.
* **Diminuir quando:** quer ser o mais competitivo possível.

---

## Política de variação por liquidez (faixa morta 5%–30%)

Esses parâmetros ajustam o **alvo** dependendo do `out_ratio` (liquidez do seu lado):

### `LOW_OUTBOUND_THRESH = 0.05`

* **O que é:** **limite inferior** (5%). Abaixo disso, você está “drenado”.
* **Efeito:** aplica **bump** (aumenta o alvo) para desincentivar saída.

### `HIGH_OUTBOUND_THRESH = 0.30`

* **O que é:** **limite superior** (30%). Acima disso, você está com “sobra” razoável.
* **Efeito:** aplica **cut** (reduz o alvo) para estimular saída.

### `LOW_OUTBOUND_BUMP = 0.05`

* **O que é:** **quanto** aumentar o alvo quando `out_ratio < 5%`.
  `0.05 = +5%` sobre o alvo.

### `HIGH_OUTBOUND_CUT = 0.05`

* **O que é:** **quanto** reduzir o alvo quando `out_ratio > 30%`.
  `0.05 = −5%` sobre o alvo.

### `IDLE_EXTRA_CUT = 0.01`

* **O que é:** **corte extra** quando o canal está **bem cheio do seu lado** ( > 60% ) **e sem forwards** nos 7 dias.
* **Valor baixo** (1%) = **quase nulo**; é um empurrãozinho para “acordar” canais ociosos.

> **Como ajustar:**
> • Se você **não quer reduzir** fee quando está drenado (ex.: `out_ratio < 5%`), mantenha `LOW_OUTBOUND_BUMP` e considere **bloquear quedas** nessa condição (feature opcional).
> • Se quer respostas mais **rápidas à liquidez**, aumente os 5% para 10–20%.

---

## Peso do volume de ENTRADA do peer (Amboss)

### `VOLUME_WEIGHT_ALPHA = 0.10`

* **O que é:** quanto o **share de entrada** do peer (nos seus canais) influencia o **seed** do Amboss.
  O script ajusta o seed para cima/baixo se esse peer envia **muito** ou **pouco** tráfego **para você**.
* **Faixa útil:** 0.0 (desliga) a 0.3 (forte).
* **Prático:** 0.10 é um **tempero leve**; 0.30 é agressivo.

---

## Circuit breaker (anti-queda de receita)

Quando você **aumenta** a fee e, em seguida, os forwards **desabam** na janela de graça, o circuito corta um pouco a fee.

### `CB_WINDOW_DAYS = 7`

* **Observação:** parâmetro “documental”. A janela efetiva já é de 7 dias pelo `LOOKBACK_DAYS`. (No código atual, `CB_WINDOW_DAYS` não é lido diretamente.)

### `CB_DROP_RATIO = 0.60`

* **O que é:** se os forwards atuais ficarem **abaixo de 60%** do “baseline” após uma alta, considera “queda forte”.

### `CB_REDUCE_STEP = 0.15`

* **O que é:** **quanto reduzir** (15%) quando o circuito dispara.

### `CB_GRACE_DAYS = 10`

* **O que é:** **período de observação** após uma subida. Se o canal performar mal dentro desse prazo, aplica o corte.

> **Dica:** se você é conservador com receita, **aumente** `CB_REDUCE_STEP` (ex.: 0.20) e/ou `CB_GRACE_DAYS` (ex.: 14).

---

## Proteção de custo de rebal (PISO)

Garante que a fee **não fique abaixo** do **custo de rebal** (para não operar no prejuízo).

### `REBAL_FLOOR_ENABLE = True`

* **Liga/desliga** essa proteção.

### `REBAL_FLOOR_MARGIN = 0.10`

* **Margem** acima do custo médio 7 d.
  Ex.: custo=700 ppm → piso = `700 * (1+0.10) = 770 ppm`.

**De onde vem o custo?**
Depende do modo abaixo:

---

## Composição do custo no ALVO

### `REBAL_COST_MODE = "per_channel" | "global" | "blend"`

* **"global"**: usa **média de custo de rebal** de **todos** os canais (últimos 7 d).
  *Bom quando há pouco rebal por canal e você quer um piso simples.*
* **"per\_channel"**: usa o custo **do próprio canal** (se houver; senão cai para o global).
  *Melhor proteção por canal — evita “subsidiar” canais mais caros com os baratos.*
* **"blend"**: mistura os dois.

### `REBAL_BLEND_LAMBDA = 0.30`

* **Só para "blend":** peso do **global**.
  Ex.: `0.30` → alvo usa **30% global + 70% por canal**.

---
# Escalada por persistência de baixo outbound (visão geral)

**Motivo de existir:**
Às vezes um canal fica **persistentemente com pouco saldo do seu lado** (`out_ratio` baixo) e **não reage** só com o ajuste de liquidez padrão (que dá um empurrão pequeno e imediato). A “escada” cria um **aumento progressivo no alvo** a cada rodada consecutiva nessa situação, até um teto. Isso:

* desincentiva ainda mais a **saída** via esse canal (quando você já está drenado);
* dá **tempo** para o mercado/rebalances corrigirem a liquidez;
* evita saltos bruscos, porque respeita o **STEP\_CAP** e tem **teto acumulado**.

> Em resumo: se o canal segue “seco” por várias rodadas, a taxa **sobe aos poucos** de forma controlada até forçar uma correção de rota/liquidez.

---

## Parâmetros

* `PERSISTENT_LOW_ENABLE` — **Liga/desliga** a escada.
  *Por que existe:* permitir experimentar ou comparar o comportamento com/sem escalada.

* `PERSISTENT_LOW_THRESH` — Limiar de **out\_ratio** abaixo do qual a rodada conta como “baixa liquidez persistente”.
  *Por que existe:* define “quando começa a doer”; use abaixo do seu `HIGH_OUTBOUND_THRESH` para detectar “baixo” antes do corte padrão.

* `PERSISTENT_LOW_STREAK_MIN` — **Número mínimo de rodadas seguidas** abaixo do limiar para **começar a aplicar** o aumento acumulado.
  *Por que existe:* evita reagir a flutuações pontuais; só age quando o problema é **persistente**.

* `PERSISTENT_LOW_BUMP` — **Incremento percentual por rodada** de streak **depois** de atingir o mínimo.
  *Por que existe:* controla o **ritmo** de escalada (ex.: +2% no alvo por rodada contínua).

* `PERSISTENT_LOW_MAX` — **Teto** para o **acumulado** da escalada (ex.: +10% máx.).
  *Por que existe:* garante que a escada **não fuja** e continue compatível com `STEP_CAP` e com a realidade do mercado.

---

### Como atua (em uma linha)

Quando `out_ratio < PERSISTENT_LOW_THRESH` por `PERSISTENT_LOW_STREAK_MIN` rodadas, o alvo é multiplicado por
`(1 + bump_acumulado)`, onde
`bump_acumulado = min(PERSISTENT_LOW_MAX, (streak - STREAK_MIN + 1) * PERSISTENT_LOW_BUMP)`.

---

### Observações importantes

* A escada **respeita `STEP_CAP`**: mesmo que o alvo suba +10%, a taxa **só anda** até o limite por rodada (ex.: 5%).
* O streak **zera** assim que `out_ratio ≥ PERSISTENT_LOW_THRESH`.
* O streak é salvo no **STATE**; ele **não avança** se você só roda em `--dry-run` (pois `STATE` não é gravado).

# Parâmetros novos do **Seed Guard** (Amboss)

## Visão geral

O *seed* é a estimativa de preço de entrada do seu peer (Amboss, métrica `incoming_fee_rate_metrics.weighted_corrected_mean`). Em mercados voláteis, essa métrica pode “espikar” e empurrar o **alvo** para valores absurdos.
O **Seed Guard** suaviza esses picos antes do seed entrar no cálculo do alvo.

> Lembrete do alvo: **target = seed\_capado + COLCHAO\_PPM**, depois ajustado por liquidez.
> O **custo de rebal** não entra no alvo — ele é usado **só como piso (floor)**, conforme `REBAL_COST_MODE`.

---

## Parâmetros novos

### `SEED_GUARD_ENABLE` *(bool)*

* **O que faz:** Liga/desliga todas as proteções do seed.
* **Padrão sugerido:** `True`
* **Quando mudar:** Desative apenas para depurar ou comparar comportamento “cru”.

---

### `SEED_GUARD_MAX_JUMP` *(float, 0–1)*

* **O que faz:** Limita o **salto máximo** do seed em relação ao **seed anterior do mesmo canal** (gravado no `STATE`).
* **Exemplo:** `0.50` ⇒ o seed desta rodada não pode crescer mais de **50%** sobre o `last_seed`.
* **Efeito prático:** Evita que um *spike* único de mercado estoure seu alvo numa única rodada.
* **Padrão sugerido:** `0.50`
* **Aperte mais se ver picos frequentes:** `0.25` (25%) ou até `0.15`.

> ⚠️ O `last_seed` **só é salvo** quando você roda **sem** `--dry-run`. Em `--dry-run`, o guard usa o histórico já gravado.

---

### `SEED_GUARD_P95_CAP` *(bool)*

* **O que faz:** Calcula o **percentil 95 (p95)** da **série 7d** do Amboss e **capa** o seed a esse p95.
* **Motivação:** Picos muito recentes costumam aparecer acima do p95 — cortar nesses casos remove outliers sem perder a tendência.
* **Padrão sugerido:** `True`
* **Quando desligar:** Se quiser ver o seed “cru” para auditoria.

---

### `SEED_GUARD_ABS_MAX_PPM` *(int ou 0)*

* **O que faz:** Define um **teto absoluto** para o seed (em ppm). Se `0` ou `None`, não aplica teto.
* **Padrão sugerido:** `2000`
* **Quando reduzir:** Se você quer uma política **sempre** abaixo de um certo nível (ex.: `1500`).
* **Quando aumentar:** Se atua em nichos de alto custo e precisa permitir seeds elevados (ex.: `3000`), lembrando que o `MAX_PPM` global ainda limita a taxa final.

---

## Como o Seed Guard decide (ordem das travas)

Para cada canal:

1. Busca série 7d do Amboss e calcula o **p65 bruto** (seed “cru”).
2. **p95-cap** (se ligado): `seed = min(seed, p95)`.
3. **Max jump vs anterior**: `seed ≤ last_seed * (1 + SEED_GUARD_MAX_JUMP)`.
4. **Teto absoluto**: `seed ≤ SEED_GUARD_ABS_MAX_PPM` (se > 0).
5. O **seed capado** vira `seed_usado` no **alvo**: `target = seed_usado + COLCHAO_PPM`.

> Dica: no relatório aparece `seed≈<valor>` e, se foi capado por qualquer trava, `seed≈<valor> (cap)`.

---

## Interações importantes

* **`COLCHAO_PPM`**: é somado ao seed **após** o guard. Aumente se quiser margem fixa maior acima do preço de entrada.
* **Liquidez (`out_ratio`)**: depois do `seed+colchão`, aplicam-se os ajustes:

  * drenado (`< LOW_OUTBOUND_THRESH`) ⇒ leve **alta**,
  * sobra (> `HIGH_OUTBOUND_THRESH`) ⇒ leve **queda**, com corte extra se estiver ocioso.
* **Rebal cost**: **não** soma no alvo. É usado **apenas como piso** via `REBAL_COST_MODE`:

  * `per_channel`: piso pelo custo do **próprio canal** (fallback para global se sem histórico),
  * `global`: piso pelo custo **global**,
  * `blend`: piso pela **mistura** `λ*global + (1-λ)*canal`.

---


## Exemplos rápidos

* **Spike absurdo no peer (tipo Kappa)**
  Config:

  ```py
  SEED_GUARD_ENABLE = True
  SEED_GUARD_MAX_JUMP = 0.25
  SEED_GUARD_P95_CAP = True
  SEED_GUARD_ABS_MAX_PPM = 1800
  ```

  Efeito: o seed não sobe mais que 25% vs rodada anterior, é cortado no p95 da série e nunca passa de 1800 ppm.

* **Ambiente estável, menos travas**

  ```py
  SEED_GUARD_ENABLE = True
  SEED_GUARD_MAX_JUMP = 0.60
  SEED_GUARD_P95_CAP = False
  SEED_GUARD_ABS_MAX_PPM = 0
  ```

  Efeito: só limita salto por histórico, aceita picos respeitando `MAX_PPM`.

---

## Boas práticas de operação

* **Rodadas “a seco” (`--dry-run`)** em cron e **aplicação real** manual/alternada:
  Você inspeciona os “cap” no seed antes de aplicar. Lembre que **dry-run não atualiza `last_seed`**.
* Se o seed **vive capado**, avalie:

  * Aumentar `COLCHAO_PPM` (se está muito “no osso”),
  * Relaxar `SEED_GUARD_MAX_JUMP` **ou** subir `SEED_GUARD_ABS_MAX_PPM`,
  * Ver se o peer realmente ficou mais caro de entrar (mudança estrutural de rota).
* Se o seed **quase nunca é capado**, mas ainda acha “alto/baixo”:

  * Ajuste `VOLUME_WEIGHT_ALPHA` (peso do volume de entrada),
  * Revise `HIGH_OUTBOUND_CUT`/`LOW_OUTBOUND_BUMP`.

---

## Tabela-resumo (valores sugeridos)

| Parâmetro                | Sugerido | Papel                                  |
| ------------------------ | -------- | -------------------------------------- |
| `SEED_GUARD_ENABLE`      | `True`   | Liga o guard                           |
| `SEED_GUARD_MAX_JUMP`    | `0.50`   | Limite +50% vs seed anterior por canal |
| `SEED_GUARD_P95_CAP`     | `True`   | Corta seed acima do p95 da série 7d    |
| `SEED_GUARD_ABS_MAX_PPM` | `2000`   | Teto absoluto do seed (0=desativa)     |



## Como escolher valores (receitas rápidas)

* **Perfil conservador (evitar prejuízo):**
  `MIN_PPM` 200–300 • `STEP_CAP` 0.03–0.05 • `COLCHAO_PPM` 30–50 • `LOW/HIGH_*` 0.05–0.10 • `REBAL_FLOOR_MARGIN` 0.10–0.20 • `REBAL_COST_MODE` = `"per_channel"`.

* **Perfil competitivo (buscar volume):**
  `MIN_PPM` 100–150 • `STEP_CAP` 0.10–0.20 • `COLCHAO_PPM` 10–20 • `LOW/HIGH_*` 0.02–0.05 • `REBAL_FLOOR_MARGIN` 0.05–0.10.

* **Cron e STEP\_CAP:**
  Rodando **mais vezes por dia** → `STEP_CAP` **menor**.
  Rodando **poucas vezes** → `STEP_CAP` **maior**.

---

# Manual do “Piso pelo Out-Rate” (`out_ppm7d`)

Este módulo opcional impede que a taxa caia **abaixo do que o canal efetivamente cobrou** nos últimos 7 dias, usando o **histórico de forwards** como um “piso” adicional. Ele se soma ao piso já existente de **custo de rebal**.

---

## Parâmetros

### `OUTRATE_FLOOR_ENABLE` (bool)

* **O que faz:** Liga/desliga o piso baseado no **out\_ppm7d** (média de ppm efetiva dos forwards de saída na janela).
* **Quando atua:** Apenas quando há forwards suficientes na janela (ver `OUTRATE_FLOOR_MIN_FWDS`).
* **Padrão sugerido:** `True`
* **Use quando:** Você quer evitar reduzir a taxa para baixo do que o canal comprovadamente conseguiu cobrar recentemente.

---

### `OUTRATE_FLOOR_FACTOR` (float, 0–1.5)

* **O que faz:** Fatora o `out_ppm7d` para formar o piso.
* **Fórmula:** `outrate_floor = ceil(out_ppm7d * OUTRATE_FLOOR_FACTOR)`
* **Efeito prático:**

  * `0.90` → **não descer** abaixo de \~90% do `out_ppm7d`.
  * `1.00` → **não descer** abaixo do `out_ppm7d` integral (mais rígido, pode “prender” a taxa).
  * `>1.00` → piso **acima** do out-rate; raramente desejável.
* **Faixa recomendada:** `0.80 – 0.95`
* **Padrão sugerido:** `0.90`

---

### `OUTRATE_FLOOR_MIN_FWDS` (int)

* **O que faz:** Exige um **mínimo de forwards** na janela para considerar `out_ppm7d` estatisticamente confiável.
* **Por quê:** Evita “grudar” taxa por causa de 1–2 forwards atípicos.
* **Padrão sugerido:** `5`
* **Ajuste conforme volume:**

  * Canais de **alto** volume: 10–20
  * Canais de **baixo** volume: 3–5

---

## Como o piso pelo out-rate se combina com o piso de rebal

* O **piso efetivo** é:
  **`floor_ppm_final = max( piso_rebal , outrate_floor )`**
* `piso_rebal` vem da sua estratégia de custo: **per\_channel**, **global** ou **blend** (com margem `REBAL_FLOOR_MARGIN`).
* Se **não houver** forwards suficientes (`fwd_count < OUTRATE_FLOOR_MIN_FWDS`) ou `out_ppm7d == 0`, **o piso pelo out-rate não atua** — vale só o piso de rebal.

---

## Ordem das etapas (resumo mental)

1. **Alvo-base**: `target_base = seed_p65 + COLCHAO_PPM`
2. **Ajuste por liquidez** (LOW/HIGH outbound) → `target`
3. **Step-cap**: aproxima taxa atual até `target` com limite de variação por rodada
4. **Pisos**:

   * Piso de **rebal** (global/per-channel/blend)
   * Piso por **out-rate** (se habilitado e com forwards suficientes)
     → **aplica o maior dos pisos**
5. **Resultado final**: `new_ppm = max(step_capped_target, floor_ppm_final)`

---

## Exemplos rápidos

### 1) Canal com histórico bom

* `out_ppm7d = 300`, `fwd_count = 12`
* `OUTRATE_FLOOR_FACTOR = 0.90` ⇒ `outrate_floor = 270`
* `piso_rebal = 220` ⇒ **piso final = 270**
* Se o `target` vier abaixo de 270, o script **não** desce além de 270.

### 2) Canal novo ou quase sem forwards

* `fwd_count = 1` (< `OUTRATE_FLOOR_MIN_FWDS`) ⇒ **piso por out-rate inativo**
* Piso vem **só do rebal** (per-channel/global/blend)
* Taxa pode cair (ou subir) sem “travar” por out\_ppm7d.

### 3) Canal caro por rebal

* `piso_rebal = 1200`, `out_ppm7d = 400`
* `outrate_floor = 360` ⇒ **piso final = 1200**
* O custo de rebal “manda” no piso — evita prejuízo ao reequilibrar.

---

## Recomendações de uso

* **Comece com:**

  ```python
  OUTRATE_FLOOR_ENABLE   = True
  OUTRATE_FLOOR_FACTOR   = 0.90
  OUTRATE_FLOOR_MIN_FWDS = 5
  ```
* Se perceber que taxas **não descem** quando o mercado esfria, reduza o **FACTOR** (ex.: 0.85).
* Se o canal tem **muito ruído** (poucos forwards na janela), aumente o **MIN\_FWDS**.
* **Evite 1.00** em `OUTRATE_FLOOR_FACTOR` se você quer que o preço siga o mercado para baixo.

---

## Dúvidas frequentes

**“Isso pode impedir quedas saudáveis de taxa?”**
Pode, se você definir um fator alto (≥1.0) ou um mínimo de forwards muito baixo — ajuste com parcimônia.

**“E se o out\_ppm7d for artificialmente alto por alguns forwards raros?”**
É por isso que existe `OUTRATE_FLOOR_MIN_FWDS`. Aumente o mínimo para exigir mais amostragem antes de ativar o piso.

**“Qual piso prevalece?”**
Sempre o **maior** entre rebal e out-rate.

---

## Exemplo numérico (cálculo do alvo)

1. **Seed (Amboss)** ajustado pelo volume do peer: `p65 = 380 ppm`.
2. **Alvo-base** = **seed + colchão** = `380 + 30 = 410 ppm`.
3. **Liquidez**: `out_ratio = 0.03` (< 0.05) ⇒ `LOW_OUTBOUND_BUMP = +5%`
   → **alvo** = `410 * 1.05 = 430,5` ⇒ **431 ppm** (arredondado).
4. **Clamp**: 431 está entre `MIN_PPM..MAX_PPM` ⇒ ok.
5. **STEP\_CAP**: fee atual = `900 ppm`. Com 5%/rodada e alvo **menor**, desce no máx. `900 * 0.05 = 45`
   → nova fee provisória = `900 − 45 = 855 ppm`.
6. **Piso de rebal**: custo=`700 ppm`, margem 10% ⇒ piso = `700 * 1,10 = 770 ppm`.
7. **Resultado final**: `max(855, 770) = 855 ppm`.
   → A fee cai de **900 → 855 ppm**, **sem** somar custo de rebal no alvo (o rebal é usado apenas como **floor**).


---

## Erros comuns (e como evitar)

* **`MIN_PPM` abaixo do custo de rebal constante:** pode vender rota no prejuízo → use **piso de rebal** ligado.
* **`STEP_CAP` alto com cron frequente:** vira “montanha-russa”; reduza para 3–5%.
* **`LOW/HIGH_OUTBOUND_*` muito agressivos:** vai “brigar” demais com a parte de custo e seed; comece com 5% e ajuste.
* **Esquecer que `BASE_FEE_MSAT` não é aplicado:** se quiser base fee ≠ 0, é preciso estender a chamada do `bos`.

---
## FAQ

**Q: Dry-run altera o `last_seed`?**
A: Não. Só salva `last_seed` (e outras métricas do STATE) quando **aplica de verdade** (sem `--dry-run`).

**Q: Vejo `seed (cap)` no relatório. O que exatamente foi capado?**
A: Pelo menos uma trava atuou (p95, salto vs anterior, ou teto absoluto). O valor mostrado já é o seed **após** o cap.

**Q: O piso (floor) ainda dispara subidas quando o rebal encarece?**
A: Sim, por design. O custo de rebal 7d protege sua margem mínima. Se esse custo sobe, o **floor** sobe. Se não quiser isso, mude `REBAL_COST_MODE` para `global` ou `blend` (mais estável), ou reduza `REBAL_FLOOR_MARGIN`.
