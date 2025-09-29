# 📚 Dicionário de Tags (com condições e o que fazer)

> Formato: **TAG** — *quando aparece* → **o que significa** → ✅ **o que fazer**

---

## 💰 Preço / Piso / Ritmo

**🧱floor-lock** — *`final_ppm == floor_ppm` e `target != floor_ppm`*
→ O **piso** (rebal floor e/ou outrate floor, já limitado por seed e teto local) **travou** sua vontade de subir/baixar.
✅ Revise custos de rebal (`REBAL_FLOOR_MARGIN`, `REBAL_COST_MODE`) e/ou `OUTRATE_FLOOR_*`. Se o piso está alto, você provavelmente **evitou prejuízo** — o que é bom.
💡 Nota: se houver **🧲peg** e o outrate for > `MAX_PPM`, o piso pode ficar **clipado no `MAX_PPM`**. Para deixar “seguir” o outrate, **aumente `MAX_PPM`** ou remova o *clamp* intermediário no cálculo do PEG (e deixe o *clamp* só no fim).

**⛔stepcap** — *`raw_step_ppm != target` (cap segurou)*
→ O *step cap* limitou a **velocidade** da mudança.
✅ Intencional para suavizar. Quer mais rapidez? Aumente `STEP_CAP` ou bônus dinâmicos (`STEP_CAP_LOW_005`, `ROUTER_STEP_CAP_BONUS` etc.).

**⛔stepcap-lock** — *`final_ppm == local_ppm` e `target != local_ppm` e `floor_ppm <= local_ppm`*
→ Você **queria mudar**, o piso não travou, mas o *step cap* **zerou o avanço** nessa rodada.
✅ Próxima execução deve andar. Se for urgente, ajuste o cap ou rode mais vezes.

**🧘hold-small** — *mudança < `BOS_PUSH_MIN_ABS_PPM` **e** < `BOS_PUSH_MIN_REL_FRAC` (sem floor forçando)*
→ Anti “micro-update”: mudança pequena demais para gastar um `bos fees`.
✅ Normal. Se quiser granularidade, diminua os limites (aceitando mais “ruído”).

**⏳cooldown…** — *janela mínima ainda não cumprida **e** `fwds_since < COOLDOWN_FWDS_MIN`*
→ Histerese anti “mexe-e-desmexe”.
✅ Aguarde mais horas/fluxo. Em **quedas** lucrativas, veja a próxima.

**⏳cooldown-profit…** — *em quedas com `margin_ppm_7d > COOLDOWN_PROFIT_MARGIN_MIN` e `fwd_count ≥ COOLDOWN_PROFIT_FWDS_MIN`*
→ Se **está lucrando** e com fluxo, **não desce tão cedo**.
✅ Bom para preservar receita; reduza se quiser buscar mais volume.

**🩹min-fix** — *`local_ppm < MIN_PPM` e foi corrigido*
→ O canal estava abaixo do **mínimo configurado**.
✅ Nada a fazer; apenas garante sanidade. Se aparecer muito, revise `MIN_PPM`.

---

## 📈 Demanda / Receita

**⚡surge+X%** — *`out_ratio < SURGE_LOW_OUT_THRESH`*
→ **Drenado** com demanda: alvo sobe (respeita *step cap*).
✅ Pode intensificar com `SURGE_K`/`SURGE_BUMP_MAX`.

**👑top+X%** — *`rev_share ≥ TOP_OUTFEE_SHARE` e `out_ratio < 0.30`*
→ Peer **relevante na receita**; protege margem.
✅ Ajuste `TOP_OUTFEE_SHARE`/`TOP_REVENUE_SURGE_BUMP`.

**💹negm+X%** — *`margin_ppm_7d < 0` e `fwd_count ≥ NEG_MARGIN_MIN_FWDS`*
→ **Rodando no prejuízo**: dá um empurrão para cima.
✅ Se recorrente, reavalie custos de rebal e metas.

**⚠️subprice** — *(`REVFLOOR_ENABLE` **e** baseline forte) **e** `final_ppm` abaixo do piso por tráfego*
→ **Subprecificando** uma super-rota.
✅ Considere elevar preço ou endurecer `REVFLOOR_*`.

**🧲peg** — *PEG do outrate ativo (OUTRATE_PEG_ENABLE) — piso colado no “preço que já vendeu” com folga `OUTRATE_PEG_HEADROOM`*
→ Evita cair **abaixo do outrate observado**; em quedas, exige **graça** maior: `OUTRATE_PEG_GRACE_HOURS`.
✅ Se o PEG te trava **abaixo** do outrate real por causa do teto, suba `MAX_PPM` ou remova o *clamp* intermediário do PEG (deixe o *clamp* só no final). Se estiver segurando quedas que você quer fazer logo, reduza `OUTRATE_PEG_GRACE_HOURS`.

---

## 🌱 Novos canais inbound / Liquidez

**🌱new-inbound** — *peer abriu o canal; `hours_since_first ≤ NEW_INBOUND_GRACE_HOURS`, `out_ratio` baixo, sem forwards e taxa atual ≫ seed*
→ **Queda mais solta** (step cap maior **só para descer**) e desliga boosts que atrapalham normalização.
✅ “Amaciar” inbound novo que chegou caro.

**🙅‍♂️no-down-low** — *`out_ratio < PERSISTENT_LOW_THRESH` e `target < local_ppm`*
→ **Bloqueia quedas** enquanto drenado/persistente.
✅ Mantém proteção de escassez.

---

## 🧪 Exploração / Descoberta

**🧪discovery** — *`DISCOVERY_ENABLE` e `fwd_count ≤ DISCOVERY_FWDS_MAX` e `out_ratio > DISCOVERY_OUT_MIN`*
→ Canal **ocioso** com outbound sobrando: acelera **quedas** (e após `DISCOVERY_HARDDROP_DAYS_NO_BASE` aplica **hard-drop**) e **desliga** floors por outrate e rebal.
✅ Bom para achar **preço de clearing**. Se cair demais, relaxe `DISCOVERY_*`.

---

## 🧬 Seed (Amboss) / Guards

**🧬seedcap:p95** — *capou no P95 da série 7d*
**🧬seedcap:prev+XX%** — *limitou salto vs seed salvo anteriormente*
**🧬seedcap:abs** — *bateu no teto absoluto (`SEED_GUARD_ABS_MAX_PPM`)*
**🧬seedcap:none** — *nenhuma trava (debug)*
→ Sanidade contra outliers.
✅ Em surtos reais, pode afrouxar com cuidado.

---

## 🧭 Classificação (fluxo)

**🏷️sink / 🏷️source / 🏷️router / 🏷️unknown** — *classe dinâmica por viés in/out + out_ratio*
**🧭bias±0.xx** — *viés EMA de saída vs entrada (debug)*
**🧭sink:0.87 / 🧭router:0.42** — *confiança da classe (0–1)*
→ Políticas finas: `SINK_*`, `SOURCE_*`, `ROUTER_*`.
✅ Ajuste limiares se houver excesso de “router”.

---

## 🛡️ Segurança / Status

**🧯 CB:** — *após subida recente, se `fwd_count < baseline*CB_DROP_RATIO`*
→ **Circuit breaker** recua parte da subida para **não matar o fluxo**.
✅ Excelente proteção; ajuste `CB_*` só se necessário.

**🟢on / 🟢back / 🔴off** — *status online/offline (cacheado)*
→ `🔴off` com `⏭️🔌 skip`: não aplica; mostra **tempo offline** e **último online**.
✅ Útil para encontrar peers “flapping”.

**🚷excl-dry** — *peer na `EXCLUSION_LIST`*
→ Apenas **simula** (linha DRY).
✅ Modo observação. `--excl-dry-tag-only` compacta a saída.

---

## 💤 stale-drain

**💤stale-drain** — *`low_streak ≥ EXTREME_DRAIN_STREAK` e `baseline_fwd7d ≤ 2`*
→ “Drenado crônico”, mas **sem demanda viva**.
✅ Reduza agressividade de subida (`PERSISTENT_LOW_BUMP`/`PERSISTENT_LOW_STREAK_MIN`), relaxe `EXTREME_DRAIN_*`, considere **deixar cair** (discovery) ou pausar estratégia nesse par.

---

## 🔎 Campo de debug final

**🔍t{target}/r{raw}/f{floor}**
→ `t` = alvo pré-stepcap; `r` = após stepcap; `f` = **piso efetivo** (inclui rebal/PEG/seed/tetos).
✅ Use o tripé para explicar “manteve”, “travou no piso”, etc.

---




