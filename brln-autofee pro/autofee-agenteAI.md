# 📘 Manual — Agente de Ajuste Automático (AutoFee IA)

Este módulo complementa o **AutoFee LND** adicionando uma camada de **IA simples** para otimizar parâmetros globais de acordo com o desempenho recente do node.

---

## 1. Conceito

O AutoFee já ajusta os **fees por canal**.
O agente `ai_param_tuner.py` atua **um nível acima**, ajustando **parâmetros globais** do script para:

* Proteger contra **subprecificação** (quando o custo de rebal > preço médio cobrado);
* Tornar o node mais ou menos **reativo** (via `STEP_CAP`, `SURGE_K`, `PERSISTENT_LOW_BUMP`);
* Evitar perda de receita em **super-rotas** (`REVFLOOR_MIN_PPM_ABS`, `OUTRATE_FLOOR_FACTOR`);
* Reduzir **ruído de updates** (`BOS_PUSH_MIN_*`);
* Aumentar **estabilidade** se circuit breakers dispararem demais (`COOLDOWN_HOURS_*`).

Os ajustes são gravados em um arquivo JSON separado:

```
/home/admin/<seu_dir>/autofee_overrides.json
```

Esse arquivo é carregado automaticamente pelo `brln-autofee-pro.py` no início da execução.
Se o arquivo **não existir ou estiver vazio**, nada acontece — o script usa os valores padrão, sem erro.

---

## 2. Como rodar o agente

### Simulação (dry-run)

Mostra as métricas de 7 dias, sintomas detectados e sugestões de ajuste, **sem gravar nada**:

```bash
python3 /home/admin/<seu_dir>/ai_param_tuner.py --dry-run
```

Exemplo de saída:

```
KPIs 7d: {'out_fee_sat': 201577, 'rebal_fee_sat': 169117, 'profit_sat': 32460, ...}
Symptoms: {'floor_lock': 0, 'no_down_low': 0, 'hold_small': 0, 'cb_trigger': 0}
Changes: {'OUTRATE_FLOOR_FACTOR': 1.03, 'REVFLOOR_MIN_PPM_ABS': 150}
[dry-run] alterações propostas (não salvas).
```

---

### Aplicação real

Grava os ajustes sugeridos no arquivo `autofee_overrides.json`:

```bash
python3 /home/admin/<seu dir>/ai_param_tuner.py
```

No próximo ciclo do AutoFee, esses overrides serão carregados e usados automaticamente.

---

## 3. Recomendação de uso

* ⏱️ **Agendamento:** rode o agente **10 minutos antes** da execução do AutoFee.
  Exemplo de cron (ajusta às xx:50, AutoFee roda às xx:00):

```cron
50 * * * * /usr/bin/python3 /home/admin/<seu_dir>/ai_param_tuner.py >> /home/admin/<seu_dir>/ai_param_tuner.log 2>&1
0  * * * * /usr/bin/python3 /home/admin/<seu_dir>/brln-autofee-pro.py >> /home/admin/<seu_dir>/autofee.log 2>&1
```

* 👀 **Modo consultivo:** se quiser apenas recomendações, rode **somente em `--dry-run`**. Assim você visualiza os ajustes sem aplicá-los.

* 🔒 **Segurança:**

  * O agente só mexe em parâmetros listados em `LIMITS`.
  * Nunca cria variáveis novas.
  * Se o JSON não existir, o AutoFee segue normal.

---

## 4. Parâmetros ajustáveis pelo agente

| Parâmetro                   | Efeito                                       |
| --------------------------- | -------------------------------------------- |
| `STEP_CAP`                  | Velocidade máxima de variação por rodada     |
| `SURGE_K`, `SURGE_BUMP_MAX` | Intensidade de subida em canais drenados     |
| `PERSISTENT_LOW_BUMP`       | Escalada em drenagem crônica                 |
| `REBAL_FLOOR_MARGIN`        | Piso de segurança relativo ao custo de rebal |
| `REVFLOOR_MIN_PPM_ABS`      | Piso adicional em super-rotas ativas         |
| `OUTRATE_FLOOR_FACTOR`      | Piso dinâmico baseado no `out_ppm7d`         |
| `BOS_PUSH_MIN_*`            | Threshold para evitar micro-updates          |
| `COOLDOWN_HOURS_*`          | Histerese mínima entre ajustes               |

---

## 5. Fluxo recomendado

1. Configure o `autofee_overrides.json` inicial com valores padrão.
2. Rode o agente em **dry-run** por alguns dias para observar recomendações.
3. Quando estiver confortável, rode **sem `--dry-run`** em cron para aplicar automaticamente.
4. Monitore `ai_param_tuner.log` para ver quais parâmetros foram ajustados.

---

## 6. Boas práticas

* Comece **conservador**: use só dry-run para observar.
* Prefira intervalos de **1× ao dia** no início, depois aumente para **1× por hora** se quiser.
* Sempre confira o **lucro líquido (`profit_sat`)** e o **profit_ppm_est** antes de liberar ajustes automáticos.
* Se o custo de rebal global estiver muito maior que os fees cobrados, force temporariamente `REBAL_COST_MODE = "global"` para proteger margem.

---

👉 Assim você tem um ciclo fechado: **AutoFee** ajusta canais, e o **Agente** regula os “botões de controle” globais de acordo com o desempenho real.

