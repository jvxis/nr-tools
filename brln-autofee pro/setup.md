# BRLN AutoFee — Ajuste automático de fees do LND

Este utilitário define/ajusta a **outgoing fee (ppm)** por canal do seu node LND de forma **data-driven**, combinando:

- **Seed por peer** (p65 de *incoming fee* do par via Amboss)
- **Custo real de rebalance** (7d, a partir do `gui_payments` do LNDg)
- **Condição de liquidez do canal** (low/high outbound, ociosidade)
- **Circuit Breaker** (recuo parcial se o tráfego cair após uma alta)
- **Step-cap** e **clamps** (limites para evitar “pulos” bruscos)

> **Dry-run**: com `--dry-run` o script **não altera nada** (nem envia Telegram).  
> **Telegram**: se configurado, envia o relatório quando **não** estiver em `--dry-run` (mensagens grandes já são quebradas automaticamente).

---

## ✨ Principais funcionalidades

- **Seed por peer (Amboss)**: usa o `incoming_fee_rate_metrics.weighted_corrected_mean` nos últimos 7 dias (p65).  
- **Rebal cost real (7d)**: `(Σ fee / Σ value) * 1e6` usando `gui_payments`.  
- **Liquidez**:
  - Outbound `< 20%` → **+25%** no alvo  
  - Outbound `> 80%` → **−20%** no alvo  
  - Ocioso (0 forwards) e outbound `> 60%` → **−10%** adicional
- **Step-cap**: variação máxima de **±20%** por rodada (exceto fee inicial = 0)
- **Circuit Breaker**: após uma **alta**, se os forwards 7d caírem abaixo de **60%** do baseline dentro de **10 dias**, aplica **−15%** no alvo
- **Clamps**: `MIN_PPM ≤ fee ≤ MAX_PPM`
- **Relatório Telegram** (opcional) com **chunking** (≈4000 chars/bloco)

---

## 🧮 Como o alvo é calculado

1. **Seed (por peer)**  
   - p65 dos últimos 7 dias do `incoming_fee_rate_metrics.weighted_corrected_mean` (Amboss)
   - Ponderado pelo **share de volume de ENTRADA** que o peer te trouxe (±30% máx)
   - Sem token Amboss → fallback `seed = 200 ppm`

2. **Alvo base**  
   - target_ppm = seed_ppm + rebal_cost_ppm_7d + COLCHAO_PPM

3. **Ajustes de liquidez (por canal)**  
- Pouco outbound → `target *= 1 + LOW_OUTBOUND_BUMP`  
- Muito outbound → `target *= 1 - HIGH_OUTBOUND_CUT`  
- Ocioso & outbound alto → `target *= 1 - IDLE_EXTRA_CUT`

4. **Limites e suavização**  
- `target_ppm = clamp(target_ppm, MIN_PPM, MAX_PPM)`  
- **Step-cap**: máx ±`STEP_CAP` relativo ao fee atual (se fee atual = 0, aplica alvo direto)

5. **Circuit Breaker**  
- Se a última ação foi **UP** e, em até `CB_GRACE_DAYS`, `forwards_7d < baseline * CB_DROP_RATIO` → reduz `CB_REDUCE_STEP`

---

## ⚙️ Parâmetros (edite no topo do script)

> **⚠️ Conferir caminhos** e preencher tokens conforme necessário.

### Caminhos
- `DB_PATH` — caminho do SQLite do **LNDg** (ex.: `/home/admin/lndg/data/db.sqlite3`)
- `LNCLI` — comando/binary do **lncli** (ex.: `"lncli"` ou um wrapper)
- `BOS` — caminho do **Balance of Satoshis** (ex.: `/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/bos`)

### Integrações
- `AMBOSS_TOKEN` — token Amboss (string JWT). **Vazio** desativa a seed (usa 200 ppm).
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT` — se **vazios**, não notifica. Se preenchidos, envia relatório quando **não** for `--dry-run`.

### Janela e caches
- `LOOKBACK_DAYS` — janela padrão para seed/forwards/rebal cost (padrão **7**)
- `CACHE_PATH` — cache de leituras Amboss (~3h)
- `STATE_PATH` — estado para circuit breaker (última direção/ppm/baseline)

### Política de fee
- `MIN_PPM` / `MAX_PPM` — limites de fee (ex.: **100** / **2500**)
- `STEP_CAP` — máx variação por rodada (ex.: **0.20** = ±20%)
- `COLCHAO_PPM` — soma fixa ao alvo (ex.: **50**)

### Liquidez
- `LOW_OUTBOUND_THRESH` — limiar para “pouco outbound” (ex.: **0.20**)
- `LOW_OUTBOUND_BUMP` — multiplicador quando pouco outbound (ex.: **+25%**)
- `HIGH_OUTBOUND_THRESH` — limiar para “muito outbound” (ex.: **0.80**)
- `HIGH_OUTBOUND_CUT` — multiplicador quando muito outbound (ex.: **−20%**)
- `IDLE_EXTRA_CUT` — corte extra se **ocioso** e outbound > 60% (ex.: **−10%**)

### Ponderação por ENTRADA (seed)
- `VOLUME_WEIGHT_ALPHA` — 0 desliga; **0.30** = ajuste moderado (±30% cap)

### Circuit Breaker
- `CB_DROP_RATIO` — ex.: **0.60** (queda para 60% do baseline dispara CB)
- `CB_REDUCE_STEP` — ex.: **0.15** (−15% no alvo quando CB aciona)
- `CB_GRACE_DAYS` — ex.: **10** dias para observar a queda pós-alta

### Exclusões (opcional)
- `EXCLUSION_LIST = set()` — adicione pubkeys para **ignorar** ajustes nesses peers

---

## ✅ Pré-requisitos

- Python 3.10+ (funciona em 3.12; datas são passadas como ISO para sqlite3)
- `requests` instalado (`pip install requests`)
- `bos` instalado e executável no caminho configurado
- Permissões para rodar `lncli listchannels` no mesmo usuário do script

---

## ▶️ Como executar

1. **Salvar e dar permissão**  
```bash
chmod +x /home/admin/brln-autofee.py
```
2. Dry-run (recomendado primeiro)
```bash
/home/admin/brln-autofee-pro.py --dry-run
```
Mostra o que faria; não grava estado; não envia Telegram

3. Valendo
```bash
/home/admin/brln-autofee.py
```
Aplica bos fees por canal; grava estado; envia Telegram (se configurado)

## 🧩 Integração com systemd (opcional)

Crie o serviço em `/etc/systemd/system/brln-autofee.service`:
```bash
[Unit]
Description=AutoFee LND (Amboss seed, liquidez e circuit-breaker)
After=network-online.target

[Service]
Type=oneshot
User=admin
ExecStart=/home/admin/brln-autofee-pro.py
WorkingDirectory=/home/admin
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```
Crie o timer em `/etc/systemd/system/brln-autofee.timer`:
```bash
[Unit]
Description=Run brln-autofee daily

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
Unit=brln-autofee.service

[Install]
WantedBy=timers.target
```
Ative:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now brln-autofee.timer
systemctl list-timers | grep brln-autofee
```
Quer rodar a cada 5 dias?
Use, por exemplo: `OnCalendar=*-*-1,6,11,16,21,26 03:15:00`

## ⏰ Alternativa com cron (opcional)
```bash
crontab -e
```
# Dry-run diário para log (03:10):
```bash
10 3 * * * /home/admin/brln-autofee-pro.py --dry-run >> /home/admin/brln-autofee_dry.log 2>&1

# Execução valendo (03:15):
15 3 * * * /home/admin/brln-autofee-pro.py >> /home/admin/brln-autofee.log 2>&1
```
## 🛠️ Troubleshooting

1. out_ratio = 0.50 em tudo
Fallback usado quando lncli listchannels não retorna capacity/local_balance.
→ Verifique LNCLI e permissões do usuário.

2. Seed muito alta em peers “premium”
Ajuste MAX_PPM, STEP_CAP e/ou reduza VOLUME_WEIGHT_ALPHA.
(Opcional: implemente um seed cap por peer no código.)

3. Sem Amboss
AMBOSS_TOKEN vazio → seed = 200 ppm (fallback conservador).

4. Telegram não chega
Confirme TELEGRAM_TOKEN/TELEGRAM_CHAT e que não está em --dry-run.
Mensagens longas já são divididas automaticamente.

5. Comando BOS falha
Cheque caminho em BOS e teste bos fees --help no mesmo usuário.

## 🗺️ Roadmap (sugestões)

Flags CLI para tunar parâmetros (ex.: --max-ppm 3000 --low-out 0.25)

Export de CSV do relatório por execução

Caps de seed por peer

Base fee (msat) dinâmica por perfil de canal