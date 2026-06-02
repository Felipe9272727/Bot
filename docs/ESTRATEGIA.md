# 📈 Estratégia SmartTrader v2

Estratégia nova, desenhada a partir de pesquisa das abordagens mais robustas
(seguidoras de tendência, confluência multi-timeframe, stops por ATR). A
filosofia é **seguir tendência com confirmação em camadas, poucos parâmetros e
risco padronizado** — robustez acima de beleza de backtest.

> ⚠️ Nenhuma estratégia garante lucro. O objetivo aqui é **robustez**: poucos
> trades ruins, risco coerente e sobrevivência. Espere win-rate de ~40-50% — a
> vantagem (se houver) vem do **risco-retorno assimétrico**, não de acertar muito.

## Fundamento (por que estas escolhas)

- **Tendência/momentum** é o efeito mais documentado academicamente: Moskowitz,
  Ooi & Pedersen (*Time Series Momentum*, 2012) e Hurst/Ooi/Pedersen (*A Century
  of Evidence on Trend-Following*) mostram persistência do efeito por décadas.
- **Confluência multi-timeframe** (confirmar no D1, executar no H1) reduz trades
  contra a maré.
- **ADX ≥ 25** separa tendência operável de lateralização (whipsaw).
- **Stops por ATR** adaptam o risco à volatilidade real (fixo em pips é errado).

Fontes: [Time Series Momentum (NYU PDF)](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) ·
[A Century of Evidence (Yale PDF)](https://fairmodel.econ.yale.edu/ec439/hurst.pdf) ·
[Turtle/Donchian](https://alchemymarkets.com/education/strategies/turtle-trading-guide/) ·
[MTF MACD+ADX+EMA200](https://medium.com/@FMZQuant/multi-timeframe-trend-trading-strategy-based-on-macd-adx-and-ema200-441835ff5bbe) ·
[ATR Trailing+ADX](https://medium.com/@FMZQuant/high-precision-atr-trailing-stop-breakout-strategy-with-adx-directional-filtering-system-d8d476e15315)

## Parâmetros (poucos e "redondos" de propósito — anti-overfitting)

| Indicador | Valor inicial | Papel |
|---|---|---|
| EMA200 (H1) | 200 | Viés de médio prazo |
| EMA50 / EMA20 (H1) | 50 / 20 | Gatilho de momentum (cruzamento) |
| Tendência D1 | Close D1 vs EMA50 D1 | Confirmação de timeframe maior |
| ADX(14) | ≥ 25 | Força de tendência |
| ATR(14) | — | Volatilidade → stops e sizing |
| MACD | 12,26,9 | Confirmação de momentum |
| Sessão | Londres–NY (13–17 GMT) | Liquidez/volume |
| Risco/trade | 0,5% – 1,0% | Sizing por ATR |

Mercados-alvo iniciais: majors (EURUSD, GBPUSD, USDJPY). Execução em **H1**, viés em **D1**.

## Regras de entrada (confluência — TODAS verdadeiras)

**COMPRA:**
1. Tendência HTF de alta: preço H1 > EMA200 **e** Close D1 > EMA50 D1
2. Alinhamento de alta: **EMA20 acima da EMA50** (estado, não o cruzamento de
   um único candle — ver nota abaixo)
3. ADX(14) ≥ 25
4. MACD: linha > sinal (gatilho de momentum)
5. Sessão = janela Londres–NY
6. Sem notícia de alto impacto na próxima 1h (ver `IA_NOTICIAS.md`)
7. **Viés da IA de notícias** permite (ver "Integração com a IA" abaixo)

**VENDA:** condições espelhadas (HTF de baixa, EMA20 abaixo da EMA50,
MACD linha < sinal, viés IA permite).

> 🛠️ **Nota de design (decidida na implementação):** usamos o **estado** de
> alinhamento `EMA20 > EMA50` em vez do **evento** de cruzamento num único
> candle. Motivo: exigir o cruzamento exato junto com "preço > EMA200 + ADX
> forte" é quase contraditório (cruzamento fresco = tendência recém-nascida;
> preço>EMA200/ADX alto = tendência madura), o que deixa a estratégia frágil e
> quase sem operar. O MACD faz o papel de gatilho de momentum e a trava de "1
> posição por símbolo" evita re-entradas em excesso. Mudança refletida em
> `smarttrader/strategy.py` e validada por testes.

## Regras de saída (100% por ATR)

- **Stop Loss** = 1,8 × ATR(14) do preço de entrada
- **TP1** = 1R (mesma distância do SL) → fecha **50%** da posição (parcial)
- Ao atingir TP1 → move o stop para **breakeven** + buffer de 0,2×ATR (cobre spread)
- Restante → **trailing por ATR** (Chandelier: máxima recente − 2,5×ATR)
- Sizing: lote = risco$ / (distância do SL × valor por unidade) — implementado em
  `smarttrader/risk.py` (`calculate_lot`)

## Integração com a IA de notícias (as duas chaves 🔑🔑)

A IA produz **direção** {ALTA, BAIXA, NEUTRO} + **confiança** (0–1) a partir das
notícias (ver `IA_NOTICIAS.md`). A estratégia técnica produz o **timing**. A
combinação dos dois é uma decisão de projeto — duas opções:

**Modo A — IA obrigatória (lidera a direção):**
- Só opera se a IA tiver convicção direcional **e** a técnica confirmar a mesma direção.
- IA NEUTRA → não opera. (A notícia "puxa o gatilho", a técnica confirma.)

**Modo B — Técnica lidera, IA veta/dimensiona (recomendação da pesquisa):**
- A técnica pode operar sozinha; a IA **veta** entradas na direção oposta
  (confiança > 0,7) e **ajusta o risco** (confiança alta → até 1,0%; baixa → 0,5%).
- IA NEUTRA / fora do ar → a técnica decide sozinha (fail-safe).

> 🔒 Em ambos os modos, a IA **nunca abre trade sozinha sem confirmação técnica**.
> A diferença é se a IA é *obrigatória* (Modo A) ou *opcional/veto* (Modo B).

### 🧭 Nota de reconciliação — Modo A x Modo B (decisão de produto em aberto)

Há uma divergência **honesta e ainda não fechada** entre duas posições:

- **Felipe escolheu o Modo A** (a IA decide a direção; a técnica confirma o timing).
- A **mesa redonda recomendou o Modo B** (técnica lidera; IA como veto/sizing) —
  ver `MESA_REDONDA.md`.

Isto é uma **decisão de produto em aberto**, não um bug. O código suporta o
**Modo A** hoje (flag `use_ai` em `trader.decide`, ver `ARQUITETURA.md`).

> ⚠️ **Ponto honesto:** enquanto a IA de notícias estiver em **stub** (o
> `NewsBiasEngine.get_bias` retorna sempre NEUTRO — ver `IA_NOTICIAS.md`), no
> **Modo A com `use_ai=true` o bot NÃO opera**: sem viés direcional da IA, não há
> direção para a técnica confirmar. Por isso o **default é `use_ai=false`** — o
> bot opera **só com a estratégia técnica** até a IA real ser plugada (Fase 4 do
> roadmap). Sem alarmismo: é factual e proposital.

## Anti-overfitting (regras de disciplina)

- Parâmetros são valores padrão da literatura, **não** otimizados par a par.
- **Não** adicionar filtro novo só porque um backtest saiu ruim (isso é curve-fitting).
- Validação obrigatória: **walk-forward** + reserva fora-de-amostra de 30%.
- Backtest **sempre com custos reais** (spread + comissão + slippage); teste de
  stress com custos +50%.
- Exigir **centenas de trades** antes de confiar em qualquer número.

Fontes anti-overfitting: [Curve Fitting](https://www.quantifiedstrategies.com/curve-fitting-in-trading/) ·
[Overfitting in Trading](https://algotrading101.com/learn/what-is-overfitting-in-trading/) ·
[Out-of-Sample Backtesting](https://arongroups.co/forex-articles/out-of-sample-backtesting/)

## Pseudo-lógica (OnTick)

```
if (NewBar() && InSession() && !NewsBlackout()) {
  htfUp  = (Close[1] > EMA200_H1) && (CloseD1 > EMA50_D1);
  trigUp = CrossUp(EMA20, EMA50) && (MACD_main > MACD_signal) && (ADX >= 25);
  aiOK_buy = AllowByAI(BUY);           // ver modo A/B
  if (htfUp && trigUp && aiOK_buy && NoOpenTrade()) {
     sl  = Ask - 1.8*ATR;
     lots = RiskLots(riskPct_byAI, Ask - sl);
     OpenBuy(lots, sl, tp1 = Ask + (Ask - sl));   // 1R; fecha 50% no TP1
  }
  // ... espelhado para venda
}
ManageOpenTrades();   // parcial no TP1, breakeven+buffer, trailing Chandelier 2.5xATR
```
