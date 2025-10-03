# Manual do “LNDg AR Trigger v2”


## O que é e por que usar?

Este script automatiza o **Auto Rebalance (AR)** por canal no LNDg: define *targets* de outbound/inbound, decide **ligar/desligar** o AR com **histerese**, respeita **custos de rebal 7d**, aplica **viés por classe** (sink/router/source/unknown), e traz dois truques úteis:

* **fill-lock**: quando está enchendo um canal, mantém o AR ligado e trava o alvo até atingir a meta;
* **cap-lock**: quando o novo alvo ficaria menor que o *out_ratio* atual (principalmente em **SINK**), ele **sobe o alvo** para o *out_ratio* atual, evitando virar **fonte** de rebal de imediato (não “perde” a liquidez que você já pagou para encher).

Tudo isso com **mensagens no Telegram** (inclui status de AR ON/OFF) e **log local** para auditoria.

---

## Visão geral do fluxo

1. **Coleta dados** dos canais via LNDg (capacidade, saldos, taxas locais/remotas, estado do AR, targets etc.).
2. **Calcula outbound global** (referência para targets por canal).
3. **Lê custos de rebal 7d** no SQLite do LNDg (por canal e global).
4. **Carrega o state/cache do AutoFee** (classe do canal, baseline de forwards, `bias_ema`, *cooldown* de liga/desliga).
5. **Define targets** (out/in) por canal:

   * global + **viés** (classe ou `bias_ema`) + **bônus por demanda** (baseline de fwds).
   * clamp seguro entre **10%** e **90%**, e no máximo **+5pp acima** do global.
   * exceção: **source** fixa **5/95**.
6. **Aplica gates**:

   * **price-gate** (sanidade de preço vs `ar_max_cost`);
   * **lucratividade** (margem L−R vs custo 7d com *safety*).
7. **Histerese & decisão**:

   * liga/desliga com banda de **±5pp**;
   * respeita **policy source = sempre OFF**;
   * **fill-lock** quando enchendo;
   * **cap-lock** quando reduzir alvo faria o canal virar fonte.
8. **Cooldown** mínimo entre trocas ON/OFF.
9. **Atualiza canal** (AR e/ou targets) e **notifica no Telegram** (+ log JSON).

---

## Parâmetros importantes (arquivo)


### Conexões e paths

* `TELEGRAM_TOKEN`, `CHATID` – onde mandar os relatórios.
* `LNDG_BASE_URL`, `username`, `password` – API do LNDg.
* `DB_PATH` – SQLite do LNDg (para custo 7d).
* `CACHE_PATH`, `STATE_PATH` – *state* do AutoFee & cooldowns.
* `AUTO_FEE_FILE`, `AUTO_FEE_PARAMS_CACHE` – origem e cache de parâmetros do AutoFee.
* `LOG_PATH` – log local (um JSON por linha).

### Limites e lógica

* `HYSTERESIS_PP = 5` – banda para ligar/desligar sem oscilar.
* `OUT_TARGET_MIN = 10`, `OUT_TARGET_MAX = 90` – guarda-chuva de segurança.
* `REBAL_SAFETY = 1.05` e `BREAKEVEN_BUFFER = 0.03` – folga de custo 7d.
* `AR_PRICE_BUFFER = 0.10` – price-gate: precisa cobrir remota com +10%.
* `MIN_REBAL_VALUE_SAT = 400_000`, `MIN_REBAL_COUNT = 3` – só confia custo 7d do **canal** se houver amostra mínima; senão usa **global**.
* `MIN_DWELL_HOURS = 2` – cooldown para trocar ON/OFF.
* `CLASS_BIAS` – viés por classe (em **fração**, ex.: `+0.12`= +12pp).
* `BIAS_MAX_PP = 12` – teto do viés dinâmico (a partir de `bias_ema`).
* `BIAS_HARD_CLAMP_PP = 20` – trava dura de segurança (pp).
* `EXCLUSION_LIST` – lista de canais ignorados.
* `FORCE_SOURCE_LIST` – força “source” em casos especiais.

### Bônus por demanda

`demand_bonus(baseline_fwds)` adiciona:

* **+8pp** se baseline ≥ 150;
* **+4pp** se baseline ≥ 50;
* **+0pp** caso contrário.

---

## Como os targets são calculados

**Fórmula (simplificada):**

```
out_target = clamp(
  min(global_out + bias + demand_bonus, global_out + 0.05),
  0.10, 0.90
)
```

* **bias** vem de `bias_ema` do AutoFee → mapeado para **pp** (±12pp padrão; clamp duro ±20pp).
  Se não houver `bias_ema`, cai no `CLASS_BIAS` (inclui **unknown** = 0pp por padrão).
* **source** ignora esse cálculo e fixa **5/95** (política: AR sempre OFF).

**cap-lock**: se `out_ratio` atual > novo `out_target`, ele **sobe o target** para `ceil(out_ratio*100)` para não criar um SINK “gordo” que vira **fonte** de rebal imediatamente após reduzir o alvo.

**fill-lock**: se o AR está **ON** e `out_ratio` < `out_target`, ele **mantém ON** e trava o alvo até atingir a meta (ignora price-gate/custo enquanto estiver enchendo).

---

## Decisão de ligar/desligar (histerese)

* **ON → OFF** se:

  * `out_ratio ≥ target + 5pp` **e** lucro OK, **ou**
  * **não lucrativo** (margem < custo 7d ajustado).
* **OFF → ON** se:

  * `out_ratio ≤ LOW_OUTBOUND_THRESH` (do AutoFee) **e** lucrativo.
* Caso contrário: **mantém** estado, respeitando o **cooldown** de 2h.

> **source**: nunca liga (policy).

---

## Gates e fórmulas

### Price-gate

> *“Se eu gastar até `ar_max_cost`%, minha taxa local ainda cobre a remota com folga?”*

```
local_ppm * (ar_max_cost/100) ≥ remote_ppm * (1 + AR_PRICE_BUFFER)
```

Padrão: **AR_PRICE_BUFFER = 10%**.

### Lucratividade (contra custo 7d)

```
margin_ppm = max(0, local_ppm - remote_ppm)
need_ppm   = ceil( cost_7d * REBAL_SAFETY ) * (1 + BREAKEVEN_BUFFER)
lucro OK   = margin_ppm ≥ need_ppm
```

* Usa **custo por canal** se amostra ≥ `MIN_REBAL_VALUE_SAT` e `MIN_REBAL_COUNT`; senão **global**.

---

## Classes de canal (comportamento)

* **sink**: viés positivo (ex.: +12pp), enche com mais agressividade.
* **router**: neutro.
* **source**: alvo fixo **5/95** e **AR sempre OFF**.
* **unknown**: tratado como **0pp** de viés (neutro), mas recebe bônus por demanda e todo restante da lógica normalmente.

> **Heurística “parece source”**: se `local_ppm == 0` **ou** (`out_ratio ≥ 0.50` e `local_ppm ≤ remote_ppm/4`), força **source** (pode ser sobreposto por `FORCE_SOURCE_LIST`).

---

## Mensagens no Telegram (como ler)

Cada atualização traz um ou mais blocos assim:

```
✅ 🛠️ TARGET Alias (chan_id)
• 🔌 AR: ON/ OFF                 ← estado do AR após a mudança
• 📊 out_ratio 0.28 • 💱 fee L/R 600/20ppm • 🧮 ar_max_cost 80%
• 🎯 alvo out/in 29/71% (fill-lock | 🧷 cap-lock | source 5/95)
• 🔎 motivo: ... price-gate ... | ... custo_7d ... | ... histerese ...
```

**Tags úteis**:

* **(fill-lock)** → enchendo; ignora gates de preço/custo até bater o alvo.
* **(🧷 cap-lock)** → alvo foi elevado ao *out_ratio* atual para preservar liquidez.
* **(source 5/95)** → política especial para canais de saída (AR OFF).

O cabeçalho do relatório também mostra:

```
⚡ LNDg AR Trigger v2 | chans=NN | global_out=0.24 | rebal7d≈485ppm | mudanças=53
```

* `mudanças` = quantas updates/targets foram aplicados nessa execução.

---

## Logs locais (auditoria)

Cada ação gera um JSON no `LOG_PATH`, por exemplo:

* `type: "update"` – quando alterou AR e/ou targets.
* `type: "targets_only"` – quando só ajustou targets.
* campos úteis: `cid`, `alias`, `out_ratio`, `local_ppm`, `remote_ppm`, `ar_max_cost`, `targets`, `price_gate_ok`, `profitable`, `class`, `baseline`, `fill_lock`, `cap_lock`, `cost_ppm`, `vol_sat_7d`, `count_7d`, etc.

---

## Execução & agendamento

* Execute manual: `python3 lndg_ar_trigger.py`
* **Cron** típico (a cada 1 hora):

  ```
  * */1 * * * /usr/bin/python3 /caminho/lndg_ar_trigger.py >> /var/log/lndg_ar_trigger.log 2>&1
  ```
* Garanta que o usuário do cron tenha acesso ao **DB**, **LNDg API** e **paths**.

---

## Boas práticas

* **Exclusion list**: use para canais que não quer que o script toque.
* **Monitore** os *mudanças* e o **rebal7d≈**; variações grandes podem indicar ruído.
* **Amostra**: se o custo 7d por canal não tiver amostra mínima, não confie nele – o script cai no custo **global** automaticamente.

---

## Erros comuns & solução rápida

### “cannot access local variable 'ar_state_txt'…”

Você já corrigiu. A regra é: **definir `ar_state_after/ar_state_txt` logo após o `update_channel()`**, independente de ter `auto_rebalance` no payload ou não.

### “PUT/PATCH … 400/405/500”

* Verifique credenciais e URL do LNDg.
* Alguns endpoints aceitam apenas **PATCH**; o script já faz fallback para PATCH.

### “Sem mudanças.”

Tudo ok! Pode ocorrer se todos os canais estiverem dentro da histerese e sem triggers.

---

## FAQ

**1) Por que às vezes ele não liga mesmo drenado?**
Porque precisa passar por **dois gates**: *price-gate* **e** *lucratividade* (margem ≥ custo 7d com folga). Se qualquer um falhar, fica OFF.

**2) Por que o alvo subiu sozinho?**
**cap-lock**. Evita que um SINK recém-enchido se torne **fonte** de rebal só porque o método de target mudou e reduziria o alvo.

**3) E se eu quiser forçar um canal a “source”?**
Inclua no `FORCE_SOURCE_LIST` **ou** deixe a heurística reconhecer (local_ppm=0, etc.). “source” mantém **AR OFF** e alvo **5/95**.

**4) O que acontece com classe “unknown”?**
É tratado como **neutro** no viés (0pp), mas recebe bônus por demanda e o restante da lógica normalmente.

---

## Glossário rápido

* **out_ratio**: fração de saldo **local/capacidade** do canal.
* **target out/in**: metas em **%** para outbound/inbound.
* **price-gate**: garantia de que, mesmo pagando até `ar_max_cost`, a taxa local cobre a remota com folga.
* **custo 7d**: custo efetivo de rebal nos últimos 7 dias (ppm).
* **fill-lock**: não solta o AR enquanto não bater o alvo ao encher.
* **cap-lock**: não deixa reduzir alvo abaixo do que o canal já tem de outbound.

---

## Dicas finais

* Ajuste **`BIAS_MAX_PP`** se quiser deixar o `bias_ema` influenciar mais/menos os alvos.
* **`AR_PRICE_BUFFER`** mais alto = mais conservador para ligar AR.
* **`BREAKEVEN_BUFFER`** controla o quão acima do “breakeven” você exige para considerar **lucrativo** (evita flapping).

