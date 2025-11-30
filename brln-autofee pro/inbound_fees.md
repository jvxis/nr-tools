# Auto-fee - Módulo de Inbound Fees (Desconto)

### ⚙️ Parâmetros principais

```python
INBOUND_FEE_ENABLE = True
```

* **O que é:** Master switch do inbound discount.
* **Se True:** o script calcula e aplica desconto na inbound fee.
* **Se False:** ignora tudo de inbound, não mexe em desconto nenhum.

---

```python
INBOUND_FEE_SINK_ONLY = True
```

* **O que é:** Define **em quais canais** o inbound discount pode ser aplicado.
* **Se True:** só aplica em canais classificados como `sink` (canais onde você costuma mandar muitos sats pra fora).
* **Se False:** permite aplicar inbound discount também em outros tipos de canais (source/router), se a lógica deixar.

*Na prática:* deixar `True` faz sentido para focar nos sinks, que são justamente onde inbound “desconto” costuma ter mais impacto.

---

```python
INBOUND_FEE_PASSIVE_REBAL_MODE = True
```

* **O que é:** Liga o modo de **rebalance passivo inteligente**.
* **Se True:**

  * Usa custo de rebal **REAL 7d** como âncora quando existir.
  * Ativa também a lógica especial de **sinks drenados sem rebal 7d** (desconto agressivo).
* **Se False:**

  * Usa um comportamento mais conservador, baseado só em margens e custos “estimados”, sem o modo agressivo/passivo.

*Tradução:* quer testar o rebalance passivo com desconto forte em sink drenado? Deixa `True`.

---

```python
INBOUND_FEE_MIN_FWDS_7D = 5
```

* **O que é:** Número mínimo de forwards nos últimos 7 dias para **considerar aplicar rebate**.
* **Onde vale:** Para a lógica normal de inbound (sinks com rebal/custo/margem).
* **Exceção:** Não é exigido no caso especial de **sink muito drenado sem rebal 7d real**.

*Uso prático:*

* Quer evitar otimizar inbound em canal que ninguém usa? Mantém 5 ou sobe.
* Quer ser mais agressivo mesmo em canais com pouco uso? Diminui esse número.

---

```python
INBOUND_FEE_MIN_MARGIN_PPM = 200
```

* **O que é:** Margem mínima (em ppm) nos últimos 7 dias para começar a dar desconto.
* **Como funciona:**

  * Se sua margem 7d (fee in − custo de rebal) < 200 ppm, o script **não dá inbound discount** (no caminho normal).
* **Onde não vale:** No modo **“drained-no-rebal”** (sink muito drenado sem rebal real), esse filtro é ignorado.

*Uso prático:*

* Isso protege contra dar desconto em canal que **não está lucrando o suficiente**.

---

```python
INBOUND_FEE_SHARE_OF_MARGIN = 0.30
```

* **O que é:** Qual fração da margem vira desconto de inbound.
* **Exemplo:**

  * Margem 7d = 1000 ppm
  * `INBOUND_FEE_SHARE_OF_MARGIN = 0.30` → desconto = 300 ppm
* Vale para o **modo normal**, não para o modo drenado/passivo.

*Ideia:* você “reparte” uma parte do lucro com quem manda liquidez de volta.

---

```python
INBOUND_FEE_MAX_FRAC_LOCAL = 0.90
```

* **O que é:** Teto relativo do desconto em relação à taxa local.
* **Exemplo:**

  * `local_ppm = 2000`, `MAX_FRAC_LOCAL = 0.9` → desconto máximo = 1800 ppm.
* Isso vale tanto para o **modo normal** quanto para o modo **drained-no-rebal**.

*Função:* garante que você nunca vai dar um desconto **quase total** sem controle.

---

```python
INBOUND_FEE_MIN_OVER_REBAL_FRAC = 1.002
```

* **O que é:** Colchão de segurança acima do custo de rebal.
* **Como funciona:**

  * net_fee (depois do desconto) tem que ser ≥ `custo_rebal * 1.002`.
  * Ou seja, sempre **um pouquinho acima** do custo, pra não sair no zero ou prejuízo arredondando.

*É o “não faça burrice por 2 sats” do sistema* 😅

---

```python
INBOUND_FEE_PUSH_MIN_ABS_PPM = 10
```

* **O que é:** Mínimo de variação no inbound discount para **mandar update pro BOS/LND**.
* **Exemplo:**

  * Se o inbound muda de 500 → 504 ppm, com limiar 10, ele **não** manda update.
  * Reduz churn de update por micro-variação.

---

### 💧 Modo especial: sinks MUITO drenados sem rebal 7d real

```python
INBOUND_FEE_DRAINED_NO_REBAL_ENABLE   = True
```

* **O que é:** Liga/desliga o modo “rebalance passivo agressivo”.
* **Se True:**

  * Para sinks MUITO drenados, sem rebal 7d real, aplica um desconto forte baseado na taxa local.
* **Se False:**

  * Esses canais voltam a ser tratados como o resto (ou nem recebem inbound discount, dependendo dos filtros).

---

```python
INBOUND_FEE_DRAINED_OUT_RATIO_MAX = 0.05
```

* **O que é:** Define o que é um sink **MUITO drenado**.
* **Se out_ratio ≤ 0.05 (5%)** e não há rebal 7d real → entra nesse modo especial.

*Tradução:* canal está praticamente seco do seu lado.

---

```python
INBOUND_FEE_DRAINED_DISCOUNT_FRAC = 0.70
```

* **O que é:** Percentual da taxa local usado como desconto no modo drenado/passivo.
* **Exemplo:**

  * `local_ppm = 3000`, fração = 0.7 → desconto = 2100 ppm
  * inbound final ≈ 900 ppm

*Aqui você controla o quão agressivo quer ser para atrair liquidez nesses sinks abandonados.*

---

```python
INBOUND_FEE_OUT_RATIO_MAX = 0.10
```

* **O que é:** Limite de out_ratio para considerar um canal “baixo” de outbound **para fins de inbound**.
* **Se out_ratio > 0.10:** nem entra na brincadeira de inbound discount.
* **Se out_ratio ≤ 0.10:** canal é considerado drenado o suficiente para pensar em desconto.

*Diferença importante:*

* `INBOUND_FEE_OUT_RATIO_MAX` = gate geral de “canal baixo/drenado” para inbound.
* `INBOUND_FEE_DRAINED_OUT_RATIO_MAX` = subset ainda mais crítico (muito drenado) para o modo agressivo passivo.

### Perfis que a gente vai comparar

1. **Sink lucrativo com rebal 7d real**
2. **Sink MUITO drenado, sem rebal 7d real (rebalance passivo)**
3. **Canal “morno” (não drenado o suficiente)** → fica **fora do inbound discount**

---

### 🧮 Tabela de comportamento por parâmetro

| Parâmetro                             | Sink lucrativo c/ rebal 7d real                                                                                                     | Sink drenado s/ rebal 7d real (passivo)                                                                     | Canal morno (fora)                                                                                |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `INBOUND_FEE_ENABLE`                  | **Precisa estar True** para qualquer desconto existir                                                                               | **Precisa estar True**                                                                                      | Se False, ninguém recebe desconto                                                                 |
| `INBOUND_FEE_SINK_ONLY`               | Se True, só aplica se o canal for classificado como `sink`                                                                          | Também precisa ser `sink`                                                                                   | Se não for sink, já é excluído aqui                                                               |
| `INBOUND_FEE_PASSIVE_REBAL_MODE`      | Se True, ancora no custo REAL de rebal 7d quando existir                                                                            | **Obrigatório** para ativar o modo “drained-no-rebal”                                                       | Se False, esse modo especial nunca entra                                                          |
| `INBOUND_FEE_MIN_FWDS_7D`             | **Usado**: exige pelo menos esse nº de forwards 7d                                                                                  | **Ignorado** nesse modo (pode ter 0 fwds)                                                                   | Se não atingir e não for “drained-no-rebal”, cai fora por `few-fwds`                              |
| `INBOUND_FEE_MIN_MARGIN_PPM`          | **Usado**: só dá desconto se a margem 7d ≥ esse valor                                                                               | **Ignorado** no modo drenado/passivo                                                                        | Se não atingir (e não entrar no modo especial), não tem desconto                                  |
| `INBOUND_FEE_SHARE_OF_MARGIN`         | **Usado**: fração da margem que vira desconto de inbound                                                                            | Não usado (aqui o desconto é baseado na taxa local, não na margem)                                          | Não tem efeito se o canal é filtrado antes                                                        |
| `INBOUND_FEE_MAX_FRAC_LOCAL`          | **Teto** do desconto relativo à taxa local                                                                                          | **Teto** também aqui: mesmo no modo agressivo, não passa disso                                              | Não usado se o canal não entra na lógica de inbound                                               |
| `INBOUND_FEE_MIN_OVER_REBAL_FRAC`     | Garante que net_fee ≥ custo_rebal × fator de segurança                                                                              | Se houver anchor de custo, ainda respeita; mas no modo drained puro, o foco é mais o `price_ppm`            | Não entra em jogo se não há inbound discount                                                      |
| `INBOUND_FEE_PUSH_MIN_ABS_PPM`        | Evita reenviar update BOS se mudança no inbound < limiar                                                                            | Mesmo comportamento                                                                                         | Se nunca há desconto, nunca há push por inbound                                                   |
| `INBOUND_FEE_DRAINED_NO_REBAL_ENABLE` | Não afeta diretamente, porque aqui **tem rebal 7d real**                                                                            | **Chave principal**: se True, ativa o modo de desconto agressivo para esse perfil                           | Mesmo que True, o canal não entra se não for drenado o suficiente                                 |
| `INBOUND_FEE_DRAINED_OUT_RATIO_MAX`   | Não se aplica: esse canal normalmente ainda pode estar drenado, mas o modo especial só olha esse corte quando **não há rebal real** | **Critério de “muito drenado”**: `out_ratio ≤ esse valor`                                                   | Se `out_ratio` acima disso, não entra no modo “drained-no-rebal”                                  |
| `INBOUND_FEE_OUT_RATIO_MAX`           | Se `out_ratio > INBOUND_FEE_OUT_RATIO_MAX`, o canal já é considerado “não drenado” e não recebe inbound discount                    | Também precisa estar `out_ratio ≤ INBOUND_FEE_OUT_RATIO_MAX` para ser elegível                              | **Principal filtro** para o “canal morno”: se `out_ratio >` esse limite, ele está fora do inbound |
| `INBOUND_FEE_DRAINED_DISCOUNT_FRAC`   | Não é usado aqui (nesse perfil o desconto vem da margem)                                                                            | **Coração do modo passivo**: desconto ≈ `price_ppm * esse_fator` (capado pelo `INBOUND_FEE_MAX_FRAC_LOCAL`) | Não entra em jogo se o canal é filtrado antes por ratio / forwards / etc.                         |



