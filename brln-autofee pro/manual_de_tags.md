# Manual das Tags — AutoFee (Amboss/LNDg/BOS)

Este manual explica **todas as tags** e ícones usados pelo script de auto-fees, com exemplos e significado prático.

---

## 1) Anatomia de uma linha

Exemplo (ação aplicada):

```
✅🔻 PeerXYZ: set 1200→930 ppm (-22.5%) | alvo 950 | out_ratio 0.62 | out_ppm7d≈410 | seed≈380 (cap) | floor≥400 | marg≈10 | rev_share≈0.06 | 🙅‍♂️no-down-low 🧬seedcap:p95 ⛔stepcap 🔍t950/r930/f400 🟢on
```

Exemplo (sem mudança):

```
🫤⏸️ PeerABC: mantém 1520 ppm | alvo 1520 | out_ratio 0.00 | out_ppm7d≈0 | seed≈602 | floor≥789 | marg≈-789 | rev_share≈0.00 | 🙅‍♂️no-down-low ⚡surge+20% 🔍t1520/r1520/f789 🟢on
```

Campos fixos:

* **set A→B ppm (±X%)**: mudança aplicada (ou “mantém” quando não muda).
* **alvo**: taxa alvo após toda a lógica.
* **out_ratio**: fração de capacidade do lado local (0.00–1.00).
* **out_ppm7d≈**: taxa *efetiva* média de saída 7d (forwards).
* **seed≈**: seed Amboss usado (com “(cap)” se houve *guard*).
* **floor≥**: piso final (rebal/OutRate).
* **marg≈**: margem 7d vs custo (positiva/negativa).
* **rev_share≈**: participação do canal na receita total (0–1).

---

## 2) Ícones de ação (início da linha)

| Ícone    | Onde           | Significado                                                |
| -------- | -------------- | ---------------------------------------------------------- |
| `✅🔺`    | set            | **Aumento** aplicado.                                      |
| `✅🔻`    | set            | **Redução** aplicada.                                      |
| `✅⏸️`    | set            | Mudança “flat” (raro; geralmente não aparece).             |
| `🫤⏸️`   | mantém         | Sem mudança (stepcap/ floor/ cooldown/ microupdate etc.).  |
| `⏭️🔌`   | skip           | Canal **offline** – ignorado nesta rodada.                 |
| `⏭️🧩`   | skip           | **Shard mismatch** (quando sharding está ligado).          |
| `🧯 CB:` | linha separada | **Circuit breaker** reduziu alvo/ritmo por queda de fluxo. |

> Observação: `DRY set ...` aparece quando você usa `--dry-run` **ou** quando o peer está em **lista de exclusão** (modo *excl-dry*).

---

## 3) Tags (final da linha)

### 3.1 Seed / Guardas do seed (Amboss)

| Tag                  | Exemplo                | Quando aparece                                     | Efeito                           |
| -------------------- | ---------------------- | -------------------------------------------------- | -------------------------------- |
| `🧬seedcap:p95`      |                        | Seed foi **capado no P95** da série 7d.            | Evita seed fora da cauda.        |
| `🧬seedcap:prev+50%` | `prev+20%`, `prev+50%` | Seed limado por **salto máximo** vs seed anterior. | Suaviza saltos entre execuções.  |
| `🧬seedcap:abs`      |                        | Seed capado no **teto absoluto** (ex.: 2000 ppm).  | Protege contra valores extremos. |
| `🧬seedcap:none`     |                        | (DEBUG) **Nenhuma** guarda aplicada ao seed.       | Informativo.                     |

> `seed≈... (cap)` no corpo indica que *alguma* guarda atuou (p95/prev/abs).

### 3.2 Liquidez / Persistência

| Tag                | Quando                                                                          | Significado                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `🙅‍♂️no-down-low` | `out_ratio < PERSISTENT_LOW_THRESH` e alvo sugere queda                         | **Bloqueia quedas** quando estamos drenados; protege liquidez.                                                                 |
| `🌱new-inbound`    | Canal novo inbound (peer abriu), alta vs seed, sem forwards, na janela de graça | **Normalização descendente acelerada** (cap maior p/ cair, ignora cooldown para quedas, sem *surge* nem persistência de alta). |

### 3.3 Step Cap / Floor

| Tag             | Condição                                                                    | Significado                                                                |
| --------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `⛔stepcap`      | `raw_step_ppm != target` na **mesma direção**                               | Step cap **limitou** a variação nesta rodada.                              |
| `⛔stepcap-lock` | `final_ppm == local_ppm` e `target != local_ppm` e `floor_ppm <= local_ppm` | Step cap **impediu qualquer mudança** (trava).                             |
| `🧱floor-lock`  | `floor_ppm >= raw_step_ppm` **e** `target > floor_ppm`                      | **Piso** (rebal/out-rate) está **dominando** — não dá para atingir o alvo. |

### 3.4 Descoberta (Discovery)

| Tag           | Quando                           | Significado                                                                         |
| ------------- | -------------------------------- | ----------------------------------------------------------------------------------- |
| `🧪discovery` | Sem forwards e liquidez sobrando | Permite **quedas mais rápidas** e **desativa** OutRate floor (prospecção de preço). |

### 3.5 Demanda/Receita (boosts)

| Tag         | Quando                                            | Significado                                                      |
| ----------- | ------------------------------------------------- | ---------------------------------------------------------------- |
| `⚡surge+X%` | Drenado (`out_ratio` muito baixo)                 | *Surge pricing* aplicou **bump** ao alvo (respeitando step cap). |
| `👑top+10%` | Canal com **grande share** da receita e baixo out | Bump extra por **top revenue**.                                  |
| `💹negm+8%` | **Margem 7d negativa** com amostra mínima         | Bump p/ recuperar margem.                                        |

### 3.6 Proteções & Ritmo

| Tag                           | Quando                                                               | Significado                                         |
| ----------------------------- | -------------------------------------------------------------------- | --------------------------------------------------- |
| `🧘hold-small`                | Delta muito pequeno (`BOS_PUSH_MIN_*`)                               | Evita **microupdates** no BOS.                      |
| `⏳cooldown4h` / `⏳cooldown8h` | Janela mínima desde última mudança **e** poucos forwards desde então | **Histerese**: segura novas alterações cedo demais. |
| `🧯 CB:` (linha separada)     | Queda de fluxo vs baseline recente                                   | **Circuit breaker** recua alvo em X%.               |

### 3.7 Estado do canal

| Tag      | Quando                             | Significado                                 |
| -------- | ---------------------------------- | ------------------------------------------- |
| `🟢on`   | Canal **online**                   | Sinal de status.                            |
| `🟢back` | Voltou a ficar online nesta rodada | Reentrada.                                  |
| `🔴off`  | **Offline**                        | (Normalmente aparece só em linhas de skip). |

### 3.8 Exclusões / Sharding / Debug

| Tag/Marca            | Onde                                  | Significado                                                                     |
| -------------------- | ------------------------------------- | ------------------------------------------------------------------------------- |
| `🚷excl-dry`         | Após o alias (`Peer: 🚷excl-dry ...`) | Peer está na **lista de exclusão** – a linha mostra **DRY** do que seria feito. |
| `⏭️🧩 ... shard ...` | Linha de skip                         | Canal não pertence ao **shard** do ciclo atual.                                 |
| `🔍t{T}/r{R}/f{F}`   | Final da linha (se `DEBUG_TAGS=True`) | Debug compacto: **t**=alvo final, **r**=stepcap aplicado, **f**=floor vigente.  |

---

## 4) Campos calculados (explicação rápida)

* **alvo** (`target`): seed ajustado por colchão, liquidez, boosts, persistências etc. **Antes** de step cap e floors.
* **raw_step** (`r` no debug): alvo **após** step cap / ritmo.
* **floor** (`f` no debug): maior entre piso de **rebal** (global/per-channel/blend + margem) e **OutRate floor** (se ativo), capado por `seed * REBAL_FLOOR_SEED_CAP_FACTOR`.
* **final_ppm**: `max(raw_step, floor)`. É a taxa efetiva proposta (pode virar “set”).
* **out_ratio**: `local_balance / capacity`.
* **out_ppm7d**: ppm médio observado nos forwards de saída (7 dias).
* **marg**: `out_ppm7d − (custo_rebal * (1+REBAL_FLOOR_MARGIN))`. Negativa ⇒ prejuízo no 7d.
* **rev_share**: fração da receita total de saída atribuída ao canal (0–1).
* **seed≈X (cap)**: seed Amboss p65 usado (com *cap* se alguma guarda atuou).

---

## 5) Casos comuns (como ler)

* **`🧱floor-lock` + `🔍.../f{alto}`**
  O piso (rebal/out-rate) está acima do passo permitido — você não “desce” além do **floor**. Para reduzir, **baixe custo de rebal** (melhor rota/valor) ou relaxe `REBAL_FLOOR_*`.

* **`⛔stepcap` / `⛔stepcap-lock`**
  O ritmo por rodada é curto. Ajuste `STEP_CAP`, `STEP_MIN_STEP_PPM` ou espere novas rodadas/forwards.

* **`🙅‍♂️no-down-low` com `out_ratio` baixo**
  Proteção contra **queda** enquanto drenado. Se quiser forçar, desative a flag ou aumente o limiar.

* **`🌱new-inbound` num canal novo com taxa alta**
  O script **ignora cooldown para quedas**, aplica **step cap maior para reduzir**, **desliga surge** e **persistência de alta** – tende a trazer rápido para perto do seed.

* **`🧘hold-small`**
  A mudança seria muito pequena – evita gasto de chamadas BOS. Se quiser mais sensibilidade, reduza `BOS_PUSH_MIN_ABS_PPM` / `BOS_PUSH_MIN_REL_FRAC`.

---

## 6) Contadores do resumo

Na 2ª linha do relatório:

* `up / down / flat`: mudanças reais aplicadas.
* `low_out`: canais com `out_ratio < PERSISTENT_LOW_THRESH`.
* `offline`: canais pulados por estarem offline.
* `shard_skips`: canais fora do shard (se sharding ligado).
* `excl_dry up/down/flat`: o que **teria** acontecido com os **excluídos**.

---

## 7) Dicas rápidas

* Ligue/desligue depuração: `DEBUG_TAGS = True/False`.
  Quando ligado, você verá `🧬seedcap:none` (sem guardas) e `🔍t/r/f` para validar lógica.
* Para “novos inbound” ficarem **menos agressivos** na queda, reduza `NEW_INBOUND_DOWN_STEPCAP_FRAC` ou `NEW_INBOUND_GRACE_HOURS`.
* Se faltar `🧱floor-lock` onde você espera, cheque `🔍t/r/f`:

  * Aparece quando `f ≥ r` **e** `t > f`.
  * Se `f ≤ r`, o floor **não** está travando (quem limitou foi step cap ou cooldown).


