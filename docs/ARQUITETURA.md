# Arquitetura do Bot (MT5 + IA em Python)

**A IA é a trader.** Um processo Python roda 24h, conecta direto no terminal
MetaTrader 5 (pacote oficial `MetaTrader5`), lê o mercado, decide com base nas
notícias + estratégia técnica, e executa as ordens ele mesmo. Sem ponte HTTP.

Este documento é o **contrato de interface** — todos os módulos seguem as
assinaturas aqui para se encaixarem.

## Visão geral

```
                  ┌─────────────────────────────────────────────┐
                  │              Processo Python (24h)           │
                  │                                              │
   notícias  ───► │  news_ai.py   ──► viés de direção (Modo A)   │
                  │       │                                      │
                  │       ▼                                      │
                  │  trader.py (laço principal) ◄── strategy.py  │
                  │       │         confirma a direção técnica    │
                  │       │                                      │
                  │       ├──► risk.py   (lote, drawdown, travas) │
                  │       │                                      │
                  │       ▼                                      │
                  │  mt5_connector.py  ──── pacote MetaTrader5 ───┼──► Terminal MT5
                  └─────────────────────────────────────────────┘        (conta DEMO)
```

## Pacote `smarttrader/`

| Módulo | Responsabilidade |
|---|---|
| `config.py` | Carrega configuração/credenciais do `.env`; parâmetros de risco e estratégia |
| `indicators.py` | EMA, ADX, ATR, MACD sobre `pandas.DataFrame` (puro, testável offline) |
| `strategy.py` | Confluência SmartTrader v2 → direção (1/-1/0); filtro de sessão |
| `risk.py` | Tamanho de lote por ATR; travas (perda diária, drawdown global, perdas seguidas) |
| `news_ai.py` | Motor de viés por notícias → {bias, confidence, blocked} (stub plugável) |
| `mt5_connector.py` | Conexão MT5: cotações, conta, abrir/modificar/fechar ordens |
| `trader.py` | Laço 24h: junta IA (direção) + estratégia (confirmação) + risco → executa |
| `backtest.py` | Backtest da estratégia em dados históricos (offline, sem dinheiro) |

## Convenção de direção/sinal

| Valor | Significado |
|-------|-------------|
| `1`   | COMPRAR |
| `-1`  | VENDER |
| `0`   | NEUTRO / não operar |

## Contratos (assinaturas)

### `indicators.py`  (puro pandas — testável sem MT5)
```python
def ema(close: pd.Series, period: int) -> pd.Series: ...
def atr(high, low, close, period: int = 14) -> pd.Series: ...
def adx(high, low, close, period: int = 14) -> pd.Series: ...
def macd(close, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series]:  # (macd_line, signal_line)
```

### `strategy.py`
```python
@dataclass
class StratParams:
    ema_trend=200; ema_slow=50; ema_fast=20
    adx_period=14; adx_min=25.0; atr_period=14
    macd_fast=12; macd_slow=26; macd_signal=9

# Confluência v2 no candle FECHADO (usar df até o penúltimo, sem look-ahead).
# df_exec: OHLC do timeframe de execução (H1). df_htf: do timeframe maior (D1).
def strategy_direction(df_exec: pd.DataFrame, df_htf: pd.DataFrame,
                       p: StratParams) -> int:  # 1 / -1 / 0

def in_session(ts, start_hour: int, end_hour: int) -> bool
```

### `risk.py`
```python
def calculate_lot(balance: float, risk_pct: float, sl_distance_price: float,
                  tick_value: float, tick_size: float,
                  min_lot: float, max_lot: float, lot_step: float) -> float

class RiskManager:
    # Mantém pico de equity, PnL diário, perdas consecutivas.
    def can_open_trade(self, equity, balance, open_positions, ...) -> tuple[bool, str]
    def register_close(self, profit: float) -> None
```

### `news_ai.py`  (contrato de IA_NOTICIAS.md)
```python
@dataclass
class Bias:
    symbol: str; bias: int   # 1/-1/0
    confidence: float        # 0..1
    blocked: bool = False    # janela de evento de alto impacto
    stale: bool = False
    rationale: str = ""

class NewsBiasEngine:
    def get_bias(self, symbol: str) -> Bias: ...   # stub agora; LLM depois
```

### `mt5_connector.py`  (precisa do MetaTrader5 — só roda no terminal do usuário)
```python
class MT5Connector:
    def connect(self, login, password, server, path=None) -> bool
    def get_rates(self, symbol, timeframe, count) -> pd.DataFrame   # OHLC
    def symbol_info(self, symbol) -> dict      # tick_value/size, min/max/step lot, digits...
    def account_info(self) -> dict             # balance, equity, ...
    def positions(self, symbol=None, magic=None) -> list
    def open_trade(self, symbol, direction, lot, sl, tp, magic, comment) -> dict
    def modify_sl(self, ticket, sl, tp=None) -> bool
    def close_partial(self, ticket, volume) -> bool
```
> Import do `MetaTrader5` é protegido (`try/except`): o módulo importa em qualquer
> SO, mas só funciona conectado a um terminal MT5 (Windows). Os demais módulos
> não dependem dele → estratégia/risco/backtest são testáveis em qualquer máquina.

### `trader.py`  (Modo A — IA decide, técnica confirma)
```python
def decide(symbol, df_exec, df_htf, bias: Bias, use_ai: bool, p) -> int:
    # use_ai: direção = bias; só opera se a técnica confirmar a MESMA direção;
    #         bias neutro/blocked/stale -> 0 (não opera).
    # !use_ai: direção = strategy_direction (permite backtest sem notícias).
```

## Regras de segurança (inegociáveis)
1. **Nunca** commitar credenciais (`.env` está no `.gitignore`).
2. Toda ordem entra com **Stop Loss** (por ATR). Sem stop, não abre.
3. Padrão: **conta DEMO**. Conta real exige flag explícita + confirmação.
4. Travas: perda diária máxima **e** drawdown global máximo desligam o bot.
5. `dry-run` (paper/log-only) disponível: decide e registra, sem enviar ordem.
