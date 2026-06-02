# 🗣️ Mesa Redonda de Especialistas — Revisão do Bot (Fase 1/2)

Quatro especialistas analisaram o código real do projeto, de forma independente.
Este documento registra o debate e as decisões que saíram dele.

| Especialista | Foco |
|---|---|
| 🧮 Quant / Estrategista técnico | Qualidade da estratégia EMA+RSI |
| 🛡️ Gestor de risco | Sobrevivência da banca |
| 🤖 Engenheiro de IA/ML | A camada de IA dá vantagem real? |
| 🎯 Cético / realista | Onde bots de varejo sangram dinheiro |

---

## ✅ Consenso (os 4 concordam)

1. **EMA+RSI sozinho não tem borda.** É a estratégia mais backtestada do varejo;
   se um cruzamento de média desse dinheiro fácil, já teria sido arbitrado.
2. **O RSI atual é decorativo.** As regras `rsi<70`/`rsi>30` quase nunca disparam
   num cruzamento — o filtro é inócuo (`Indicators.mqh:86,90`).
3. **A borda real está em GESTÃO DE RISCO e CONTROLE DE CUSTO, não no indicador.**
4. **Falta trava de drawdown GLOBAL** — só existe a diária (`MaxDailyLossPercent`).
   Dá pra sangrar a banca em fatias diárias sem nada desligar o EA. *Buraco crítico.*
5. **Backtest sem custos = ilusão.** Spread + comissão + slippage corroem a borda;
   precisa entrar no teste desde o dia 1.
6. **Validação séria** = walk-forward, fora de amostra, amostra grande (200+ trades,
   vários regimes), e demo longa antes de pensar em dinheiro real.

---

## 🔥 O grande debate: o papel da IA

**3 dos 4 convergiram, sozinhos, na mesma posição:**

> A IA **não deve dar o gatilho de entrada.** No máximo deve (a) filtrar regime
> ("é um bom momento pra esse trade?") e (b) ajudar a dimensionar o lote.

Motivos levantados:
- **Train/serve skew** (engenheiro de IA): as features são calculadas em dois lugares
  diferentes — MQL4 na produção (`AIBridge.mqh:128-130`) e Python no treino. `iMA`
  do MT4 e o EMA do pandas divergem. O modelo recebe em produção dados diferentes
  dos que viu no treino. *É a armadilha que mais mata modelos reais.*
- **Validação cega** (cético): o WebRequest não roda no Strategy Tester, então hoje
  validamos com `UseAI=false` e operamos com `UseAI=true` — **validando um sistema
  e operando outro.**
- **Teatro de complexidade** (quant): exigir `confidence>0.60` de um número não
  calibrado é placebo; 3 filtros lineares transparentes são mais robustos
  out-of-sample que um ML opaco em localhost que ainda adiciona ponto de falha.

**Implicação:** isso muda a arquitetura atual (onde técnico e IA precisam concordar
pra entrar). Decisão registrada abaixo.

---

## ⚔️ Tensões (onde discordaram)

- **Risco 1% fixo vs decrescente** (gestor de risco): defende reduzir o risco após
  perdas consecutivas (1% no pico, 0,5% após 2 perdas, 0,25% após 4), porque perdas
  vêm em cluster (regime), não independentes. Risco fixo otimiza pro caso médio;
  sobrevivência exige otimizar pro cluster ruim.
- **ML necessário?** (engenheiro de IA vs quant): um diz que ML como *filtro de
  regime* tem valor; o outro diz que pra este escopo ML é desnecessário e regras
  bem feitas batem o modelo. Consenso possível: **só ML se provar valor em
  walk-forward líquido de custos.**

---

## 📋 Plano de ação priorizado (saída do debate)

### P0 — Risco (CRÍTICO, fazer primeiro)
- [ ] **Max drawdown GLOBAL** que desliga o EA (input `MaxAccountDDPercent`, guardar
      pico de equity em `GlobalVariable`).
- [ ] **Contador de perdas consecutivas** → bloqueia no dia após N perdas.
- [ ] **Risco decrescente** após sequência de perdas (opcional, debate em aberto).
- [ ] **Breakeven automático** após X pips de lucro.
- [ ] **Validar margem livre** (`AccountFreeMarginCheck`) antes de abrir.
- [ ] Endurecer `DailyProfit` contra histórico paginado/incompleto.

### P1 — Estratégia / robustez
- [ ] **Filtro ADX** anti-chop (não operar em lateral) — maior impacto/menor esforço.
- [ ] **SL/TP por ATR** (dinâmico) em vez de pips fixos.
- [ ] **Filtro de tendência por EMA de timeframe maior** (operar a favor da maré).
- [ ] **Consertar o RSI**: exigir RSI>50 pra comprar, <50 pra vender (momentum real).
- [ ] **Janela de sessão** (operar só Londres+NY; bloquear sexta tarde/notícias).

### P2 — IA (reposicionar)
- [ ] **Cache de 1 chamada por candle** (não por tick) — elimina latência/freeze.
- [ ] **Feature spec único e versionado** (`ai/features.py`) + teste MQL4 vs Python.
- [ ] **Features estacionárias** (distâncias/retornos normalizados, não níveis absolutos).
- [ ] **Rebaixar IA para filtro de regime + sizing**, não gatilho de entrada.
- [ ] **Persistir todas as predições** (auditoria de skew e decay).

### P3 — Processo / disciplina
- [ ] Backtest **sempre com custos** (spread realista + comissão).
- [ ] **Walk-forward** em janelas deslizantes (não só in/out simples).
- [ ] **Demo 3-6 meses** com o sistema completo antes de cogitar real.
- [ ] **Diário de operações** (spread real, slippage, motivo de cada trade).

---

## 🧭 Decisão do moderador (síntese)

A conclusão honesta da mesa: **a prioridade não é "deixar o bot mais esperto",
é deixá-lo mais difícil de quebrar.** A ordem de trabalho é Risco (P0) → Robustez
da estratégia (P1) → reposicionar IA (P2) → disciplina de processo (P3).

A IA não é jogada fora — é **rebaixada de "decide a entrada" para "filtra e
dimensiona"**, e só ganha espaço se provar valor em walk-forward líquido de custos.

> ⚠️ Nada disso promete lucro. O objetivo de todas as mudanças é **robustez e
> sobrevivência** — reduzir trades ruins e padronizar risco. Lucro, se vier, é
> consequência de sobreviver tempo suficiente pra borda (se houver) aparecer.
