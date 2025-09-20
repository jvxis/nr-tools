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

## Como escolher valores (receitas rápidas)

* **Perfil conservador (evitar prejuízo):**
  `MIN_PPM` 200–300 • `STEP_CAP` 0.03–0.05 • `COLCHAO_PPM` 30–50 • `LOW/HIGH_*` 0.05–0.10 • `REBAL_FLOOR_MARGIN` 0.10–0.20 • `REBAL_COST_MODE` = `"per_channel"`.

* **Perfil competitivo (buscar volume):**
  `MIN_PPM` 100–150 • `STEP_CAP` 0.10–0.20 • `COLCHAO_PPM` 10–20 • `LOW/HIGH_*` 0.02–0.05 • `REBAL_FLOOR_MARGIN` 0.05–0.10.

* **Cron e STEP\_CAP:**
  Rodando **mais vezes por dia** → `STEP_CAP` **menor**.
  Rodando **poucas vezes** → `STEP_CAP` **maior**.

---

## Exemplo numérico (cálculo do alvo)

1. **Seed (Amboss)** ajustado pelo volume do peer: `p65 = 380 ppm`.
2. **Custo de rebal (per\_channel)** 7 d: `700 ppm`.
3. **Colchão:** `+30` → `380 + 700 + 30 = 1.110 ppm`.
4. **Liquidez:** `out_ratio = 0.03` (< 0.05) ⇒ `LOW_OUTBOUND_BUMP = +5%`
   → alvo `1.110 * 1.05 = 1.165 ppm`.
5. **Clamp:** dentro de `MIN..MAX`, então segue.
6. **STEP\_CAP:** fee atual é `900 ppm`. Com 5%/rodada, novo vai para
   `900 + 5% de 900 = 945 ppm` (ainda **abaixo** do alvo, vai subindo aos poucos nas próximas execuções).
7. **Piso de rebal:** custo=700 ppm, margem 10% → piso `770 ppm`.
   `945` > `770` → ok.

---

## Erros comuns (e como evitar)

* **`MIN_PPM` abaixo do custo de rebal constante:** pode vender rota no prejuízo → use **piso de rebal** ligado.
* **`STEP_CAP` alto com cron frequente:** vira “montanha-russa”; reduza para 3–5%.
* **`LOW/HIGH_OUTBOUND_*` muito agressivos:** vai “brigar” demais com a parte de custo e seed; comece com 5% e ajuste.
* **Esquecer que `BASE_FEE_MSAT` não é aplicado:** se quiser base fee ≠ 0, é preciso estender a chamada do `bos`.

---

