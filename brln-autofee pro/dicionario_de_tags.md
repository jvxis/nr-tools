# 📚 Dicionário de Tags (com condições e o que fazer)

> Formato de cada item:
> **TAG** — *quando aparece* → **o que significa** → ✅ **o que fazer**

---

## 💰 Preço / Piso / Ritmo

**🧱floor-lock** — *`final_ppm == floor_ppm` e `target != floor_ppm`*
→ O **piso** (rebal floor e/ou outrate floor, já limitado por seed) **travou** sua vontade de subir/baixar.
✅ Revise custos de rebal (`REBAL_FLOOR_MARGIN`, `REBAL_COST_MODE`) e/ou `OUTRATE_FLOOR_*`. Se o piso está alto, você provavelmente **evitou prejuízo** — o que é bom.

**⛔stepcap** — *`raw_step_ppm != target` (cap segurou)*
→ O *step cap* limitou a **velocidade** da mudança.
✅ Isso é intencional para suavizar. Se quiser reagir mais rápido, aumente `STEP_CAP` ou os bônus dinâmicos (ex.: `STEP_CAP_LOW_005`, `ROUTER_STEP_CAP_BONUS`).

**⛔stepcap-lock** — *`final_ppm == local_ppm` e `target != local_ppm` e `floor_ppm <= local_ppm`*
→ Você **queria mudar**, o piso não travou, mas o *step cap* **zerou o avanço** nessa rodada.
✅ Próxima execução deve andar. Se estiver urgente, ajuste cap ou use execuções mais frequentes.

**🧘hold-small** — *mudança < `BOS_PUSH_MIN_ABS_PPM` **e** < `BOS_PUSH_MIN_REL_FRAC` (sem floor forçando)*
→ Anti “micro-update”: mudança pequena demais para valer um `bos fees`.
✅ Normal. Se quiser granularidade, diminua esses limites — com o risco de “ruído”.

**⏳cooldown…** — *janela mínima ainda não cumprida **e** `fwds_since < COOLDOWN_FWDS_MIN`*
→ Histerese: evita “mexe-e-desmexe”.
✅ Aguarde mais horas/fluxo. Para queda em rota lucrativa há regras ainda **mais conservadoras** (ver a próxima).

**⏳cooldown-profit…** — *em quedas com `margin_ppm_7d > COOLDOWN_PROFIT_MARGIN_MIN` e `fwd_count ≥ COOLDOWN_PROFIT_FWDS_MIN`*
→ Se **está lucrando** e com fluxo, **não desce tão cedo**.
✅ Excelente para preservar receita; reduza a fricção se quiser perseguir mais volume.

---

## 📈 Demanda / Receita

**⚡surge+X%** — *`out_ratio < SURGE_LOW_OUT_THRESH`*
→ **Drenado** com demanda: empurra o alvo para cima (respeitando *step cap*).
✅ Sinal saudável; pode intensificar com `SURGE_K`/`SURGE_BUMP_MAX`.

**👑top+X%** — *`rev_share ≥ TOP_OUTFEE_SHARE` e `out_ratio < 0.30`*
→ Peer **relevante na sua receita**; protege sua margem.
✅ Bom para cash-cows. Ajuste `TOP_OUTFEE_SHARE`/`TOP_REVENUE_SURGE_BUMP` conforme seu perfil.

**💹negm+8%** — *`margin_ppm_7d < 0` e `fwd_count ≥ NEG_MARGIN_MIN_FWDS`*
→ Está **rodando no prejuízo**: dá um empurrão para cima.
✅ Se aparecer muito, reavalie custo de rebal, alvos e peers.

**⚠️subprice** — *(`REVFLOOR_ENABLE` **e** `baseline_fwd7d ≥ REVFLOOR_BASELINE_THRESH`) **e** `final_ppm < max(int(seed*0.90), int(max(seed*0.40, REVFLOOR_MIN_PPM_ABS)))`*
→ **Preço abaixo** do “piso por tráfego” para **super-rota** (canal muito ativo).
✅ Você pode estar **deixando dinheiro na mesa**. Considere elevar `final_ppm` (ou aumentar `REVFLOOR_MIN_PPM_ABS` / reduzir `TOP_OUTFEE_SHARE` se poucas rotas concentram receita). Se isso aparecer com frequência, seu **seed** pode estar modesto para a demanda real.

---

## 🌱 Novos canais inbound / Liquidez

**🌱new-inbound** — *canal recém-aberto pelo peer (janela `NEW_INBOUND_GRACE_HOURS`), `out_ratio` baixíssimo, sem forwards, e taxa atual bem acima do seed*
→ Ativa **queda mais solta** (step cap maior **só para descer**) e **desliga** boosts/persistências que poderiam atrapalhar a normalização.
✅ Serve para “amaciar” inbound novo que chegou caro.

**🙅‍♂️no-down-low** — *`out_ratio < PERSISTENT_LOW_THRESH` e `target < local_ppm`*
→ **Bloqueia quedas** enquanto drenado/persistente: não jogue contra si mesmo.
✅ Ótimo “freio de burrice”.

---

## 🧪 Exploração / Descoberta

**🧪discovery** — *`DISCOVERY_ENABLE` e `fwd_count ≤ DISCOVERY_FWDS_MAX` e `out_ratio > DISCOVERY_OUT_MIN`*
→ Canal **ocioso** com muita saída sobrando — o script afrouxa pisos por *out_ppm* e acelera quedas (hard-drop após `DISCOVERY_HARDDROP_DAYS_NO_BASE`).
✅ Ajuda a **achar o preço de clearing**. Se exagerar nas quedas, relaxe `DISCOVERY_*`.

---

## 🧬 Seed (Amboss) / Guards

**🧬seedcap:p95** — *capou no P95 da série 7d*
**🧬seedcap:prev+XX%** — *limitou salto vs seed salvo anteriormente*
**🧬seedcap:abs** — *bateu no teto absoluto (`SEED_GUARD_ABS_MAX_PPM`)*
**🧬seedcap:none** — *nenhuma trava (debug)*
→ Sanidade contra outliers de seed.
✅ Em surtos de mercado, você pode suavizar guardas (com cautela).

---

## 🧭 Classificação (fluxo)

**🏷️sink / 🏷️source / 🏷️router / 🏷️unknown** — *classificação dinâmica por viés in/out + limites de out_ratio*
**🧭bias±0.xx** — *valor do viés (debug)*
→ Políticas finas por classe: `SINK_*`, `SOURCE_*`, `ROUTER_*`.
✅ Ajuste limiares se estiver “rotulando demais como router”.

---

## 🛡️ Segurança / Status

**🧯 CB:** — *após subida recente, se `fwd_count < baseline*CB_DROP_RATIO`*
→ **Circuit breaker**: recua parte da subida para **não matar o fluxo**.
✅ Excelente rede de proteção. Ajuste `CB_*` apenas se tiver certeza.

**🟢on / 🟢back / 🔴off** — *status online/offline (cacheado)*
→ `🔴off` com `⏭️🔌 skip`: nada é aplicado, relatório mostra **tempo offline** e **último online**.
✅ Útil para caçar peers flapping.

**🚷excl-dry** — *peer na `EXCLUSION_LIST`*
→ Apenas **simula** (linha DRY).
✅ Modo “observação”. `--excl-dry-tag-only` deixa a saída **compacta**.

---

## 💤 stale-drain

**💤stale-drain** — *`low_streak ≥ EXTREME_DRAIN_STREAK` (ex.: 20) **e** `baseline_fwd7d ≤ 2`*
→ O canal **parece drenado** há muito tempo (streak alto), mas **não tem baseline de forwards** — ou seja, **drenagem “velha/estagnada” sem tráfego real recente**.
**Tradução:** você está tratando como “drenadão crônico”, porém **não há demanda viva suficiente** para justificar agressividade.

✅ **O que fazer:**

* **Reduza agressividade** de subida: baixar `PERSISTENT_LOW_BUMP` ou subir `PERSISTENT_LOW_STREAK_MIN`.
* **Relaxe o “Extreme drain”**: aumentar `EXTREME_DRAIN_STREAK` ou desligar `EXTREME_DRAIN_ENABLE` **para esse perfil**.
* **Verifique o par**: rota pode ter **secado**; considere *descoberta* (deixar cair) ou mesmo **excluir temporariamente** da estratégia.
* **Cheque seed/guardas**: se o seed está alto e sem tráfego, você pode estar super-precificando baseado em histórico antigo.

---

## 🔎 Campo de debug final

**🔍t{target}/r{raw}/f{floor}**
→ `t` = alvo calculado antes do *step cap*; `r` = alvo após *step cap*; `f` = **piso efetivo**.
✅ Leia esse tripé para entender **por que** a linha resultou em “manteve”, “travou no piso”, etc.

---

## 🧩 Exemplos focados nas novas tags

**(1) `⚠️subprice` numa super-rota**

```
✅⏸️ PeerX: mantém 420 ppm | alvo 380 | out_ratio 0.18 | out_ppm7d≈520 | seed≈360 | floor≥410 | marg≈+90 | rev_share≈0.24 | 👑top+12% ⚠️subprice 🔍t380/r380/f410 🟢on
```

— O piso de **super-rota** puxa você para ≥410; abaixo disso é **subprecificação**.
**Ação:** aceite ≥410 ou ajuste `REVFLOOR_*`.

**(2) `💤stale-drain` (drenado sem vida)**

```
🫤⏸️ PeerY: mantém 620 ppm | alvo 650 | out_ratio 0.02 | out_ppm7d≈8 | seed≈590 | floor≥600 | marg≈-592 | 💤stale-drain ⛔stepcap 🔍t650/r620/f600 🟢on
```

— Streak alto mas **quase sem forwards**.
**Ação:** diminua agressividade de “drenado crônico” e reavalie o caso (talvez **deixar cair** para descobrir preço).

---


