# 🤖 SmartTrader — Bot de Trading para MetaTrader 5 (a IA é a trader)

Bot de operações automatizadas em **Python comandando o MetaTrader 5**. A IA
lê o mercado (e, quando plugada, **notícias macro**), decide a direção e executa
as ordens ela mesma, 24h. Construído para ser **testado com segurança** (testes
+ backtest + conta demo) antes de qualquer dinheiro real.

> ⚠️ **Aviso:** trading tem risco real de perda. Nenhum bot garante lucro. Este
> projeto te dá disciplina (segue estratégia, controla risco, opera sem emoção),
> mas o resultado depende da estratégia e do mercado. **Sempre teste em demo.**

## Como funciona

```
notícias ─► news_ai ─► viés de direção ┐
                                        ├─► trader (Modo A) ─► mt5_connector ─► MT5 (DEMO)
preço ────► strategy ─► confirma direção┘         │
                                          risk (lote, drawdown, travas)
```

- **A IA decide a direção** (a partir de notícias macro); a **estratégia técnica
  confirma** o timing. Só opera quando as duas concordam (Modo A).
- Roda **direto em Python** via o pacote oficial `MetaTrader5` — sem ponte HTTP.

## Estrutura

```
smarttrader/
  config.py         # configuração via .env
  indicators.py     # EMA, ATR, ADX, MACD (pandas puro)
  strategy.py       # confluência SmartTrader v2 -> direção
  risk.py           # lote por ATR + travas (perda diária, drawdown, perdas seguidas)
  news_ai.py        # motor de viés por notícias (stub plugável)
  news_sources.py   # ingestão: RSS / GDELT / calendário Finnhub
  news_mapper.py    # raciocínio macro->direção (crise no petróleo -> ativo)
  mt5_connector.py  # conexão e execução no MT5
  trader.py         # laço 24h (a IA é a trader)
  backtest.py       # backtest offline com custos
tests/              # 88 testes (rodam em qualquer SO, sem MT5)
docs/               # arquitetura, estratégia, IA de notícias, mesa redonda, instalação
```

## Testar (do mais seguro ao mais real)

**1. Offline, qualquer PC (sem MT5, sem dinheiro):**
```bash
make venv && make test        # roda os 88 testes
make backtest                 # backtest de exemplo (dados sintéticos)
```

**2. No Windows com MT5 (conta DEMO):** veja [`docs/INSTALACAO_MT5.md`](docs/INSTALACAO_MT5.md)
```bash
python -m smarttrader.trader --once   # com DRY_RUN=true: mostra a decisão sem operar
```

**3. Dinheiro real:** só depois da demo provar valor — e com sua autorização.

## Roadmap

- [x] Fase 0 — Arquitetura, estratégia (pesquisada) e contratos
- [x] Fase 1 — Núcleo Python: indicadores, estratégia v2, risco, config (testado)
- [x] Fase 2 — Conector MT5 + laço do trader + backtest + CI
- [x] Fase 3 — Esqueleto da IA de notícias (sources, mapper, motor de viés)
- [ ] Fase 4 — Plugar IA real (FinBERT + LLM) no seu dispositivo
- [ ] Fase 5 — Backtest com dados REAIS + validação fora-de-amostra
- [ ] Fase 6 — Demo prolongada (3-6 meses)
- [ ] Fase 7 — (Só após aprovação) conta real com travas

Documentação: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) ·
[`docs/ESTRATEGIA.md`](docs/ESTRATEGIA.md) ·
[`docs/IA_NOTICIAS.md`](docs/IA_NOTICIAS.md) ·
[`docs/MESA_REDONDA.md`](docs/MESA_REDONDA.md) ·
[`docs/INSTALACAO_MT5.md`](docs/INSTALACAO_MT5.md)
