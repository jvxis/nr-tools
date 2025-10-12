# ⚙️ AI Param Tuner — Manual do Operador de Node Roteador

> 🧠 **Objetivo:**
> O *AI Param Tuner* é um assistente inteligente que ajusta automaticamente os parâmetros do script **AutoFee** com base no comportamento real do seu node.
> Ele analisa as métricas dos últimos 7 dias e propõe ajustes graduais para **maximizar lucro e utilização do outbound**, mantendo a rede saudável e evitando overreaction.

---

## 📊 1. Como o AI Tuner funciona

O Tuner roda diariamente (ou manualmente com `--dry-run`) e executa 5 etapas:

1. **Coleta de KPIs (7 dias):**

   * Lucro, volume roteado e custo de rebal.
2. **Leitura de sintomas:**

   * Analisa o log do AutoFee (`autofee-apply.log`) para entender o comportamento dos canais.
3. **Avaliação de tendência:**

   * Mede se o node está em sequência boa (*good streak*) ou ruim (*bad streak*).
4. **Cálculo de ajustes:**

   * Decide se deve endurecer ou relaxar pisos, cooldowns e sensibilidades.
5. **Aplicação controlada:**

   * Só grava as mudanças se estiver dentro do **budget diário** e do **cooldown mínimo**.

---

## 🧩 2. O que o operador deve observar

Durante a operação, há dois conjuntos de informações importantes:

### 🧮 KPIs (métricas de 7 dias)

| Métrica            | Significado                              | Interpretação                     |
| ------------------ | ---------------------------------------- | --------------------------------- |
| `out_ppm7d`        | Preço médio das rotas saindo do node     | Alta = caro / Baixa = competitivo |
| `rebal_cost_ppm7d` | Custo médio dos rebalances               | Alta = está gastando muito        |
| `profit_sat`       | Lucro líquido em sats nos últimos 7 dias | Negativo = node ineficiente       |
| `profit_ppm_est`   | Margem estimada (ppm_out - ppm_rebal)    | Ideal entre **0 e 200 ppm**       |
| `margin_ppm`       | Diferença absoluta entre out e rebal     | Menor que 0 = prejuízo            |

➡️ **Meta:** manter `profit_ppm_est ≥ 0` e usar **>80%** do outbound por dia.

---

### 🩺 Sintomas (detectados nos logs)

| Emoji | Nome          | Significado                          | Ação Sugerida                         |
| ----- | ------------- | ------------------------------------ | ------------------------------------- |
| 🧱    | `floor_lock`  | Muitos canais travados por piso alto | Reduzir `REBAL_FLOOR_MARGIN`          |
| 🙅‍♂️ | `no_down_low` | Nenhum canal abaixando taxa          | Aumentar `SURGE_K` e `SURGE_BUMP_MAX` |
| 🧘    | `hold_small`  | Canais pequenos “presos”             | Reduzir `BOS_PUSH_MIN_ABS_PPM`        |
| 🧯    | `cb_trigger`  | Circuit breaker ativado              | Aumentar `COOLDOWN_HOURS_DOWN`        |
| 🧪    | `discovery`   | Muitos canais testando preço         | Evitar subir `OUTRATE_FLOOR_FACTOR`   |

---

## ⚙️ 3. Configurações principais

### 🧾 Defaults (valores padrão)

Esses valores são seguros e funcionam bem para a maioria dos **nodes roteadores**:

| Parâmetro               | Descrição                                    | Valor Default | Efeito esperado                     |
| ----------------------- | -------------------------------------------- | ------------- | ----------------------------------- |
| `STEP_CAP`              | Passo máximo de ajuste de taxa por rodada    | `0.05`        | Evita saltos bruscos                |
| `SURGE_K`               | Sensibilidade à demanda                      | `0.50`        | 0.3 = lenta / 0.7 = reativa         |
| `SURGE_BUMP_MAX`        | Teto máximo de aumento temporário            | `0.20`        | Protege contra over-shoot           |
| `PERSISTENT_LOW_BUMP`   | Incremento se canal está cronicamente barato | `0.05`        | Mantém taxa mínima ativa            |
| `PERSISTENT_LOW_MAX`    | Limite máximo de bump persistente            | `0.20`        | Limita exagero em lows              |
| `REBAL_FLOOR_MARGIN`    | Margem mínima de ROI no rebal                | `0.10`        | Evita pagar caro para rebalancear   |
| `REVFLOOR_MIN_PPM_ABS`  | Piso mínimo absoluto de taxa                 | `500`         | Evita rotas abaixo do custo         |
| `OUTRATE_FLOOR_FACTOR`  | Multiplicador sobre o preço observado        | `1.10`        | Aumenta margem média                |
| `BOS_PUSH_MIN_ABS_PPM`  | PPM mínimo para push do BOS                  | `15`          | Evita push de canais baratos demais |
| `BOS_PUSH_MIN_REL_FRAC` | Fração mínima relativa para push             | `0.04`        | Mantém proporcionalidade            |
| `COOLDOWN_HOURS_DOWN`   | Tempo mínimo entre quedas de taxa            | `6`h          | Evita flutuações rápidas            |
| `COOLDOWN_HOURS_UP`     | Tempo mínimo entre subidas de taxa           | `3`h          | Dá tempo para mercado reagir        |
| `REBAL_BLEND_LAMBDA`    | Peso dado ao custo de rebal no cálculo       | `0.30`        | Balanceia preço vs. custo           |
| `NEG_MARGIN_SURGE_BUMP` | Incremento extra se margem negativa          | `0.05`        | Reage a prejuízo leve               |

---

### 🔒 Limites (LIMITS)

| Parâmetro               | Mín  | Máx  | Comentário                             |
| ----------------------- | ---- | ---- | -------------------------------------- |
| `STEP_CAP`              | 0.02 | 0.15 | Maior = mais agressivo                 |
| `SURGE_K`               | 0.20 | 0.90 | Alta = mais sensível                   |
| `SURGE_BUMP_MAX`        | 0.10 | 0.50 | Aumente só se node está “trancando”    |
| `PERSISTENT_LOW_BUMP`   | 0.03 | 0.12 | Evita bump eterno                      |
| `PERSISTENT_LOW_MAX`    | 0.10 | 0.40 | Segurança contra overprice             |
| `REBAL_FLOOR_MARGIN`    | 0.05 | 0.30 | ROI mínimo por rebal                   |
| `REVFLOOR_MIN_PPM_ABS`  | 100  | 700  | Protege contra preço baixo             |
| `OUTRATE_FLOOR_FACTOR`  | 0.75 | 1.35 | Define a faixa de sensibilidade global |
| `BOS_PUSH_MIN_ABS_PPM`  | 5    | 20   | Mínimo absoluto de push                |
| `BOS_PUSH_MIN_REL_FRAC` | 0.01 | 0.06 | Ajuste fino do push                    |
| `COOLDOWN_HOURS_DOWN`   | 3    | 12   | Espera mínima entre reduções           |
| `COOLDOWN_HOURS_UP`     | 1    | 8    | Espera mínima entre aumentos           |
| `REBAL_BLEND_LAMBDA`    | 0.0  | 1.0  | Peso do custo de rebal                 |
| `NEG_MARGIN_SURGE_BUMP` | 0.05 | 0.20 | Incremento reativo ao prejuízo         |

---

### ⏱️ Cooldowns e histerese

| Configuração                 | Valor | Função                                    |
| ---------------------------- | ----- | ----------------------------------------- |
| `MIN_HOURS_BETWEEN_CHANGES`  | 4     | Tempo mínimo entre execuções válidas      |
| `REQUIRED_BAD_STREAK`        | 2     | Rodadas negativas seguidas para endurecer |
| `REQUIRED_GOOD_STREAK`       | 2     | Rodadas positivas seguidas para aliviar   |
| `RELIEF_HYST_NEG_MARGIN_MIN` | 150   | Alívio imediato se margem ≤ -150 ppm      |
| `RELIEF_HYST_FLOORLOCK_MIN`  | 120   | Floor-locks altos disparam alívio         |
| `RELIEF_HYST_WINDOWS`        | 3     | Janelas consecutivas para permitir alívio |

---

### 💰 Budget diário (DAILY_CHANGE_BUDGET)

Controla quanto cada parâmetro pode mudar **por dia**, limitando volatilidade.

| Parâmetro               | Máx. variação diária | Explicação                        |
| ----------------------- | -------------------- | --------------------------------- |
| `OUTRATE_FLOOR_FACTOR`  | 0.05                 | Pequenas variações diárias        |
| `REVFLOOR_MIN_PPM_ABS`  | 60 ppm               | Piso pode subir até 60 ppm/dia    |
| `REBAL_FLOOR_MARGIN`    | 0.08                 | Ajuste máximo de ROI diário       |
| `STEP_CAP`              | 0.03                 | Limita aceleração de taxas        |
| `SURGE_K`               | 0.15                 | Sensibilidade diária do surge     |
| `SURGE_BUMP_MAX`        | 0.08                 | Teto diário de bump               |
| `PERSISTENT_LOW_BUMP`   | 0.02                 | Aumento gradual para lows         |
| `PERSISTENT_LOW_MAX`    | 0.06                 | Expansão limitada de persistência |
| `BOS_PUSH_MIN_ABS_PPM`  | 6                    | Push controlado por dia           |
| `BOS_PUSH_MIN_REL_FRAC` | 0.01                 | Proporção de push diário          |
| `COOLDOWN_HOURS_UP`     | 1                    | Pode reduzir até 1h/dia           |
| `COOLDOWN_HOURS_DOWN`   | 2                    | Pode reduzir até 2h/dia           |
| `REBAL_BLEND_LAMBDA`    | 0.20                 | Rebalance ponderado               |
| `NEG_MARGIN_SURGE_BUMP` | 0.03                 | Incremento de correção suave      |

---

## 📘 4. Como configurar na prática

1. **Primeira execução:**

   ```bash
   python3 ai_param_tuner.py --dry-run --telegram
   ```

   → Verifique se as mensagens no Telegram fazem sentido (nenhum valor absurdo).

2. **Rodar em produção (cron):**

   ```bash
   0 */1 * * * /usr/bin/python3 /home/admin/nr-tools/brln-autofee pro/ai_param_tuner.py
   ```

   → Idealmente juntamente com a frequência do auto fee dia.

3. **Monitorar comportamento:**

   * Observe `profit_ppm_est` e `floor_lock` no log do Telegram.
   * Se o node mantiver lucro leve e rotas estáveis → o Tuner está calibrado.

4. **Resetar o estado:**

   * Para reiniciar aprendizado, apague:

     ```bash
     rm -f ~/.cache/auto_fee_state.json
     rm -f /home/admin/nr-tools/brln-autofee pro/autofee_meta.json
     ```
   * O script recria os arquivos automaticamente.

---

## 🧠 5. Dicas avançadas

* **Discovery alto (🧪 > 50):**
  indica mercado instável — evite subir `OUTRATE_FLOOR_FACTOR`.

* **Floor-lock alto e lucro baixo:**
  o Tuner entrará em *Plano A*, reforçando pisos e ROI.

* **Lucro alto + discovery alto:**
  ativa *afrouxar_por_good_streak_discovery*, reduzindo piso e cooldown para expandir volume.

* **CB triggers repetidos (🧯):**
  sinal de saturação — reduza `STEP_CAP` ou aumente `COOLDOWN_HOURS_DOWN`.

---

## 🧾 6. Resumo prático: parâmetros-chave do roteador

| Objetivo               | Parâmetro principal             | Direção ideal                       |
| ---------------------- | ------------------------------- | ----------------------------------- |
| Aumentar volume        | ↓ `OUTRATE_FLOOR_FACTOR`        | Rotas mais baratas                  |
| Proteger lucro         | ↑ `REVFLOOR_MIN_PPM_ABS`        | Piso absoluto mais alto             |
| Reduzir custo de rebal | ↑ `REBAL_FLOOR_MARGIN`          | Rebalance só quando ROI vale a pena |
| Acelerar ajustes       | ↓ `COOLDOWN_HOURS_UP` / `DOWN`  | Reações mais rápidas                |
| Reduzir ruído diário   | ↓ budgets (DAILY_CHANGE_BUDGET) | Mais estabilidade                   |

---

## 🧩 7. Conclusão

O **AI Param Tuner** é um *autopiloto de inteligência adaptativa* para nodes roteadores.
Ele **aprende o padrão de lucro e movimento**, aplicando heurísticas para que seu node:

✅ use todo o outbound diariamente,
✅ mantenha margens positivas, e
✅ evite gasto excessivo com rebalances.

> 💬 **Recomendação:**
> Execute sempre em `--dry-run` nas primeiras 3 rodadas e acompanhe as mensagens no Telegram antes de liberar a gravação real.


