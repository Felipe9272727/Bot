"""Indicadores técnicos puros (pandas/numpy), testáveis offline.

Este módulo NÃO depende do pacote MetaTrader5 nem da biblioteca `ta`. Todas as
funções recebem `pandas.Series`/colunas OHLC e retornam `pandas.Series`
alinhadas ao índice de entrada. Os valores iniciais que não podem ser
calculados (período de aquecimento) ficam como NaN, conforme convenção dos
indicadores de Wilder/EMA.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, period: int) -> pd.Series:
    """Média Móvel Exponencial (EMA) com ``adjust=False``.

    Usa o fator de suavização alpha = 2/(period+1). Com ``adjust=False`` a
    recursão é a forma clássica usada em trading: ``ema_t = alpha*close_t +
    (1-alpha)*ema_{t-1}``.

    Parâmetros
    ----------
    close : pd.Series
        Série de preços (tipicamente o fechamento).
    period : int
        Período da EMA (> 0).

    Retorna
    -------
    pd.Series
        EMA alinhada ao índice de ``close``.
    """
    if period <= 0:
        raise ValueError("period deve ser > 0")
    return close.ewm(span=period, adjust=False).mean()


def _wilder_smoothing(series: pd.Series, period: int) -> pd.Series:
    """Suavização de Wilder (RMA): EMA com alpha = 1/period, ``adjust=False``.

    É a base do ATR e do ADX clássicos. Equivalente a
    ``series.ewm(alpha=1/period, adjust=False).mean()``.
    """
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range (TR) candle a candle.

    TR = max(high-low, |high-close_anterior|, |low-close_anterior|). Na primeira
    barra (sem close anterior) usa apenas ``high-low``.
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # primeira barra: sem close anterior -> apenas high-low
    tr.iloc[0] = (high.iloc[0] - low.iloc[0]) if len(tr) else tr
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (ATR) com suavização de Wilder.

    Calcula o True Range e aplica a suavização de Wilder (RMA) com o período
    informado. As primeiras barras (aquecimento) tendem a NaN/instáveis até a
    suavização "encher".

    Parâmetros
    ----------
    high, low, close : pd.Series
        Colunas OHLC alinhadas no mesmo índice.
    period : int
        Período do ATR (padrão 14).

    Retorna
    -------
    pd.Series
        ATR alinhado ao índice de entrada.
    """
    if period <= 0:
        raise ValueError("period deve ser > 0")
    tr = true_range(high, low, close)
    return _wilder_smoothing(tr, period)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX clássico de Wilder.

    Passos: calcula +DM/-DM e TR; suaviza por Wilder; deriva +DI/-DI; calcula
    DX = 100*|+DI − −DI|/(+DI + −DI); e o ADX é a suavização de Wilder do DX.

    Retorna apenas a série do ADX (não +DI/-DI), conforme o contrato. As barras
    de aquecimento ficam como NaN.

    Parâmetros
    ----------
    high, low, close : pd.Series
        Colunas OHLC alinhadas no mesmo índice.
    period : int
        Período do ADX (padrão 14).

    Retorna
    -------
    pd.Series
        ADX alinhado ao índice de entrada.
    """
    if period <= 0:
        raise ValueError("period deve ser > 0")

    up_move = high.diff()
    down_move = -low.diff()

    # +DM: só conta quando o movimento de alta supera o de baixa (e é positivo)
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    # -DM: só conta quando o movimento de baixa supera o de alta (e é positivo)
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    tr = true_range(high, low, close)

    atr_w = _wilder_smoothing(tr, period)
    plus_dm_w = _wilder_smoothing(plus_dm, period)
    minus_dm_w = _wilder_smoothing(minus_dm, period)

    # +DI / -DI; evita divisão por zero
    plus_di = 100.0 * (plus_dm_w / atr_w.replace(0.0, np.nan))
    minus_di = 100.0 * (minus_dm_w / atr_w.replace(0.0, np.nan))

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum

    adx_series = _wilder_smoothing(dx.fillna(0.0), period)
    # mantém NaN onde DX era indefinido no começo (aquecimento)
    adx_series = adx_series.where(dx.notna() | (adx_series.index != adx_series.index[0]))
    return adx_series


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """MACD: retorna ``(macd_line, signal_line)``.

    ``macd_line = EMA(fast) − EMA(slow)`` e ``signal_line = EMA(macd_line,
    signal)``, todas com ``adjust=False`` (EMA clássica).

    Parâmetros
    ----------
    close : pd.Series
        Série de preços (fechamento).
    fast, slow, signal : int
        Períodos do MACD (padrão 12, 26, 9).

    Retorna
    -------
    tuple[pd.Series, pd.Series]
        (linha MACD, linha de sinal), alinhadas ao índice de ``close``.
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("períodos devem ser > 0")
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line
