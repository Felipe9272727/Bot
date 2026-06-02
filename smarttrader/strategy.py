"""Estratégia SmartTrader v2 — confluência multi-timeframe → direção (1/-1/0).

Implementa as regras de ``docs/ESTRATEGIA.md`` decidindo SEMPRE no candle
FECHADO (sem look-ahead). Convenção: a ÚLTIMA linha de ``df_exec``/``df_htf`` é
o candle fechado mais recente — o chamador NÃO deve passar o candle em
formação.

Depende apenas de ``smarttrader.indicators`` (puro pandas/numpy), sem MT5.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import indicators as ind


@dataclass
class StratParams:
    """Parâmetros da estratégia (valores padrão da literatura, anti-overfitting).

    Os defaults seguem o contrato em ``docs/ARQUITETURA.md``.
    """

    ema_trend: int = 200       # EMA de viés de médio prazo (H1)
    ema_slow: int = 50         # EMA lenta do cruzamento (e EMA de tendência do HTF)
    ema_fast: int = 20         # EMA rápida do cruzamento
    adx_period: int = 14       # período do ADX
    adx_min: float = 25.0      # força mínima de tendência
    atr_period: int = 14       # período do ATR (stops/sizing)
    macd_fast: int = 12        # MACD rápido
    macd_slow: int = 26        # MACD lento
    macd_signal: int = 9       # MACD sinal


def _htf_trend(df_htf: pd.DataFrame, p: StratParams) -> int:
    """Tendência do timeframe maior na última barra fechada do HTF.

    Regra (contrato HTF_EMA=50): close > EMA(ema_slow) -> 1; < -> -1; == -> 0.
    Retorna 0 se não houver dados suficientes ou houver NaN.
    """
    if df_htf is None or len(df_htf) < 1:
        return 0
    close = df_htf["close"]
    ema_htf = ind.ema(close, p.ema_slow)
    last_close = close.iloc[-1]
    last_ema = ema_htf.iloc[-1]
    if pd.isna(last_close) or pd.isna(last_ema):
        return 0
    if last_close > last_ema:
        return 1
    if last_close < last_ema:
        return -1
    return 0


def strategy_direction(df_exec: pd.DataFrame, df_htf: pd.DataFrame, p: StratParams) -> int:
    """Direção da confluência SmartTrader v2 no candle fechado.

    A última linha de ``df_exec``/``df_htf`` é o candle fechado mais recente.

    COMPRA (1) — todas verdadeiras:
      - price > emaTrend (EMA200 H1) na última barra;
      - htf_trend == 1 (close HTF > EMA50 HTF);
      - alinhamento de alta: emaFast > emaSlow (ESTADO, não o cruzamento de um
        único candle — ver nota de design abaixo);
      - macd_line > signal_line na última barra (gatilho de momentum);
      - adx >= adx_min na última barra.

    Nota de design: usamos o ESTADO ``emaFast > emaSlow`` em vez do evento de
    cruzamento exato. Exigir o cruzamento no candle exato, junto com
    ``price > EMA200`` e ADX forte, é quase contraditório (cruzamento fresco =
    tendência recém-nascida; preço>EMA200/ADX alto = tendência já madura) e
    deixa a estratégia frágil/inerte. O alinhamento + MACD (momentum) + a trava
    de "1 posição por símbolo" no trader dão entradas robustas sem re-entrada
    em excesso. Ver docs/ESTRATEGIA.md.

    VENDA (-1): condições espelhadas. Caso contrário, 0.

    Protege contra séries curtas/NaN: retorna 0 se faltar dado.
    """
    # validação básica de entrada
    if df_exec is None or len(df_exec) < 2:
        return 0
    cols = {"open", "high", "low", "close"}
    if not cols.issubset(df_exec.columns):
        return 0

    high = df_exec["high"]
    low = df_exec["low"]
    close = df_exec["close"]

    # precisamos de pelo menos 2 barras para detectar cruzamento
    n = len(close)
    if n < 2:
        return 0

    # --- indicadores no candle fechado (última barra) ---
    ema_trend = ind.ema(close, p.ema_trend)
    ema_fast = ind.ema(close, p.ema_fast)
    ema_slow = ind.ema(close, p.ema_slow)
    macd_line, signal_line = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    adx_series = ind.adx(high, low, close, p.adx_period)

    price = close.iloc[-1]
    last_ema_trend = ema_trend.iloc[-1]

    fast_now, fast_prev = ema_fast.iloc[-1], ema_fast.iloc[-2]
    slow_now, slow_prev = ema_slow.iloc[-1], ema_slow.iloc[-2]

    macd_now = macd_line.iloc[-1]
    signal_now = signal_line.iloc[-1]
    adx_now = adx_series.iloc[-1]

    htf_trend = _htf_trend(df_htf, p)

    # se qualquer valor essencial for NaN, não opera
    essenciais = [
        price, last_ema_trend, fast_now, fast_prev, slow_now, slow_prev,
        macd_now, signal_now, adx_now,
    ]
    if any(pd.isna(v) for v in essenciais):
        return 0

    # Alinhamento das EMAs (ESTADO), não o cruzamento de um único candle.
    # fast_prev/slow_prev são lidos apenas para garantir >=2 barras válidas.
    fast_above = fast_now > slow_now
    fast_below = fast_now < slow_now

    adx_ok = adx_now >= p.adx_min

    # --- COMPRA ---
    if (
        price > last_ema_trend
        and htf_trend == 1
        and fast_above
        and macd_now > signal_now
        and adx_ok
    ):
        return 1

    # --- VENDA (espelhado) ---
    if (
        price < last_ema_trend
        and htf_trend == -1
        and fast_below
        and macd_now < signal_now
        and adx_ok
    ):
        return -1

    return 0


def in_session(ts, start_hour: int, end_hour: int) -> bool:
    """Verifica se ``ts`` está dentro da janela de sessão [start_hour, end_hour).

    - ``ts``: ``datetime``/``pd.Timestamp``; usa a hora (0..23).
    - Janela normal: ``start <= hora < end``.
    - ``start == end``: filtro desativado -> sempre True.
    - Janela cruzando a meia-noite (``start > end``): True se ``hora >= start``
      OU ``hora < end`` (ex.: 22..6).

    Retorna
    -------
    bool
    """
    hour = pd.Timestamp(ts).hour

    if start_hour == end_hour:
        # filtro desativado: opera 24h
        return True

    if start_hour < end_hour:
        return start_hour <= hour < end_hour

    # janela cruzando a meia-noite (start > end)
    return hour >= start_hour or hour < end_hour
