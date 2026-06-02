# 🤖 SmartTrader — Bot de Trading para MetaTrader 4

Bot de operações automatizadas para **MetaTrader 4**, com análise técnica e
uma camada opcional de **Inteligência Artificial**. Construído para ser
**testado com segurança** (backtest + conta demo) antes de qualquer dinheiro real.

> ⚠️ **Aviso importante:** trading envolve risco real de perda. Nenhum bot
> garante lucro. Este projeto te dá uma ferramenta **disciplinada** (segue
> estratégia, controla risco, opera sem emoção), mas o resultado depende da
> estratégia e das condições de mercado. **Sempre teste em demo primeiro.**

## Por que MT4 + IA externa?

O MT4 roda robôs (Expert Advisors) em MQL4 e tem um **Strategy Tester**
embutido — dá pra simular anos de mercado com dinheiro fake. A IA roda
**fora** do MT4, em um serviço Python no seu dispositivo, e o EA conversa
com ela via HTTP local. Assim o bot funciona só com técnica e ganha o
"cérebro" de IA quando você quiser.

Veja [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) para o desenho completo.

## Estrutura

```
mql4/
  Experts/SmartTraderEA.mq4   # O robô (roda dentro do MT4)
  Include/Indicators.mqh      # Sinais de análise técnica
  Include/RiskManager.mqh     # Gestão de risco e tamanho de lote
  Include/AIBridge.mqh        # Ponte com o serviço de IA
ai/
  server.py                   # Serviço de IA (HTTP local)
  model.py                    # Onde o modelo de IA é plugado
  requirements.txt
docs/
  ARQUITETURA.md              # Contrato de interface
  INSTALACAO.md               # Como instalar e rodar
  BACKTEST.md                 # Como testar no Strategy Tester
```

## Roadmap por fases

- [x] **Fase 0** — Fundação, arquitetura e contratos de interface
- [ ] **Fase 1** — EA técnico funcional + gestão de risco (backtestável)
- [ ] **Fase 2** — Ponte de IA + serviço Python stub (testável ponta a ponta)
- [ ] **Fase 3** — Modelo de IA real plugado (você roda no seu dispositivo)
- [ ] **Fase 4** — Otimização, validação em demo prolongada
- [ ] **Fase 5** — (Só após aprovação) ligar conta real com travas de segurança

## Começando

1. Leia [`docs/INSTALACAO.md`](docs/INSTALACAO.md)
2. Compile o EA no MetaEditor e rode no **Strategy Tester** (demo)
3. Veja [`docs/BACKTEST.md`](docs/BACKTEST.md) para interpretar resultados

**Status atual:** Fase 0 concluída. Fase 1 em construção.
