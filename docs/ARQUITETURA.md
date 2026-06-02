# Arquitetura do Bot (MT4 + IA)

Este documento é o **contrato de interface** do projeto. Todos os módulos
seguem os nomes e assinaturas definidos aqui para que se encaixem sem conflito.

## Visão geral

```
┌─────────────────────────────────────────────────────────┐
│                     MetaTrader 4                          │
│                                                           │
│   ┌─────────────────────────────────────────────┐        │
│   │         SmartTraderEA.mq4 (Expert)           │        │
│   │  - OnTick(): laço principal de decisão        │       │
│   │  - combina sinal técnico + sinal de IA        │       │
│   │  - abre/fecha ordens, trailing, etc.          │       │
│   └───────┬───────────────┬──────────────┬────────┘       │
│           │               │              │                │
│   ┌───────▼─────┐ ┌───────▼──────┐ ┌─────▼────────┐       │
│   │Indicators.  │ │RiskManager.  │ │ AIBridge.mqh │       │
│   │   mqh       │ │   mqh        │ │ (WebRequest) │       │
│   └─────────────┘ └──────────────┘ └─────┬────────┘       │
└──────────────────────────────────────────┼───────────────┘
                                            │ HTTP localhost
                                  ┌─────────▼──────────┐
                                  │  ai/server.py      │
                                  │  Serviço de IA      │
                                  │  (modelo plugável)  │
                                  └────────────────────┘
```

## Convenção de sinais

Todas as funções de sinal retornam um inteiro padronizado:

| Valor | Significado |
|-------|-------------|
| `1`   | COMPRAR (sinal de alta) |
| `-1`  | VENDER (sinal de baixa) |
| `0`   | NEUTRO / não operar |

## Contrato dos módulos MQL4

### `Include/Indicators.mqh`
Sinais de análise técnica puros (sem estado de conta).
```mql4
// Retorna 1 / -1 / 0 conforme convenção de sinais.
int  GetTechnicalSignal(string symbol, int timeframe);
// Helpers individuais (úteis para a IA também):
double GetRSI(string symbol, int timeframe, int period);
double GetEMA(string symbol, int timeframe, int period);
```

### `Include/RiskManager.mqh`
Dimensionamento de posição e travas de segurança.
```mql4
// Lote calculado para arriscar 'riskPercent'% do saldo dado o stop em pips.
double CalculateLotSize(string symbol, double riskPercent, double stopLossPips);
// Trava global: respeita nº máx de posições, perda diária máx, etc.
bool   CanOpenTrade(int magic);
// Normaliza lote aos limites do símbolo (min/max/step).
double NormalizeLot(string symbol, double lot);
```

### `Include/AIBridge.mqh`
Comunicação com o serviço de IA externo via `WebRequest`.
```mql4
// Consulta o serviço de IA. Retorna 1 / -1 / 0. Em erro/timeout retorna 0.
int    GetAISignal(string symbol, int timeframe);
// Liga/desliga o uso da IA (se desligado, GetAISignal retorna 0 sem chamar).
extern bool UseAI;            // input do EA
extern string AIServerURL;    // ex.: "http://127.0.0.1:5000/signal"
```

## Contrato do serviço de IA (`ai/server.py`)

Endpoint HTTP local. O EA envia features de mercado, recebe uma decisão.

**Requisição** `POST /signal`
```json
{
  "symbol": "EURUSD",
  "timeframe": 15,
  "features": { "rsi": 48.2, "ema_fast": 1.0832, "ema_slow": 1.0840,
                "price": 1.0835, "spread": 0.8 }
}
```

**Resposta**
```json
{ "signal": 1, "confidence": 0.72 }
```
- `signal`: 1 / -1 / 0 (mesma convenção)
- `confidence`: 0.0 a 1.0 — o EA pode exigir confiança mínima

O modelo de IA é plugável: a função `predict(features)` em `ai/model.py`
é o ponto onde Claude/usuário conecta o modelo treinado. O `server.py`
funciona com um modelo "stub" (regras simples) até o modelo real existir,
para que tudo seja **testável desde o dia 1**.

## Regras de segurança (inegociáveis)
1. **Nunca** commitar credenciais, chaves de API ou senhas.
2. EA sempre opera com **Stop Loss** definido — sem ordem sem stop.
3. Padrão de execução: **conta DEMO**. Conta real exige mudança explícita
   de parâmetro e confirmação do usuário.
4. Trava de **perda diária máxima** que desliga o bot no dia.
