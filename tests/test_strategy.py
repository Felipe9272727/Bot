"""Testes da estratégia SmartTrader v2 e dos indicadores.

Gera DataFrames sintéticos para exercitar:
- tendência de alta clara (crossUp + htf de alta + adx alto) -> espera 1;
- tendência de baixa -> espera -1;
- mercado lateral/ruído -> espera 0;
- filtro de sessão (dentro, fora, cruzando meia-noite, desativado);
- sanidade dos indicadores (tamanho da série e robustez com poucos dados).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smarttrader import indicators as ind
from smarttrader.strategy import StratParams, in_session, strategy_direction


# ---------------------------------------------------------------------------
# Helpers de geração de dados sintéticos
# ---------------------------------------------------------------------------

def _ohlc_from_close(close: np.ndarray, index: pd.DatetimeIndex, spread: float) -> pd.DataFrame:
    """Constrói um DataFrame OHLC plausível a partir de uma série de fechamento."""
    close = np.asarray(close, dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=index,
    )


def _make_exec_uptrend(n: int = 300) -> pd.DataFrame:
    """Tendência de alta: longa fase plana (acumula EMAs juntas) e depois subida
    forte que gera cruzamento da EMA20 acima da EMA50 na última barra."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    base = np.full(n, 100.0)
    # fase final de aceleração para forçar crossUp recente
    accel = np.linspace(0, 30, 40)
    base[-40:] = 100.0 + accel
    return _ohlc_from_close(base, idx, spread=0.05)


def _make_exec_downtrend(n: int = 300) -> pd.DataFrame:
    """Tendência de baixa espelhada: fase plana e queda forte ao final."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    base = np.full(n, 100.0)
    accel = np.linspace(0, 30, 40)
    base[-40:] = 100.0 - accel
    return _ohlc_from_close(base, idx, spread=0.05)


def _make_exec_sideways(n: int = 300, seed: int = 7) -> pd.DataFrame:
    """Mercado lateral/ruído em torno de um nível, sem tendência."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    base = 100.0 + np.cumsum(rng.normal(0.0, 0.05, n))
    # mantém em torno de 100 (mean reversion forte)
    base = 100.0 + (base - base.mean()) * 0.3
    return _ohlc_from_close(base, idx, spread=0.05)


def _make_htf(direction: int, n: int = 120) -> pd.DataFrame:
    """HTF (D1) claramente de alta (1), baixa (-1) ou neutro (0)."""
    idx = pd.date_range("2023-06-01", periods=n, freq="D")
    if direction == 1:
        close = 100.0 + np.linspace(0, 50, n)
    elif direction == -1:
        close = 200.0 - np.linspace(0, 50, n)
    else:
        close = np.full(n, 100.0)  # plano -> close ~ ema -> neutro
    return _ohlc_from_close(close, idx, spread=0.1)


# ---------------------------------------------------------------------------
# Testes de strategy_direction
# ---------------------------------------------------------------------------

def test_uptrend_returns_buy():
    """Tendência de alta clara + HTF de alta -> COMPRA (1)."""
    p = StratParams()
    df_exec = _make_exec_uptrend()
    df_htf = _make_htf(1)
    assert strategy_direction(df_exec, df_htf, p) == 1


def test_downtrend_returns_sell():
    """Tendência de baixa clara + HTF de baixa -> VENDA (-1)."""
    p = StratParams()
    df_exec = _make_exec_downtrend()
    df_htf = _make_htf(-1)
    assert strategy_direction(df_exec, df_htf, p) == -1


def test_sideways_returns_neutral():
    """Mercado lateral/ruído -> NEUTRO (0)."""
    p = StratParams()
    df_exec = _make_exec_sideways()
    df_htf = _make_htf(0)
    assert strategy_direction(df_exec, df_htf, p) == 0


def test_uptrend_but_htf_against_blocks():
    """Alta no exec, mas HTF de baixa -> bloqueia COMPRA (não 1)."""
    p = StratParams()
    df_exec = _make_exec_uptrend()
    df_htf = _make_htf(-1)
    assert strategy_direction(df_exec, df_htf, p) != 1


def test_insufficient_data_returns_zero():
    """Séries curtas -> 0 (sem explodir)."""
    p = StratParams()
    idx = pd.date_range("2024-01-01", periods=1, freq="h")
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]}, index=idx)
    assert strategy_direction(df, df, p) == 0
    assert strategy_direction(df.iloc[0:0], df, p) == 0


def test_missing_columns_returns_zero():
    """Faltando colunas OHLC -> 0."""
    p = StratParams()
    idx = pd.date_range("2024-01-01", periods=5, freq="h")
    df = pd.DataFrame({"close": np.arange(5.0)}, index=idx)
    assert strategy_direction(df, df, p) == 0


# ---------------------------------------------------------------------------
# Testes de in_session
# ---------------------------------------------------------------------------

def test_in_session_dentro():
    """Hora dentro da janela Londres-NY (13-17)."""
    assert in_session(pd.Timestamp("2024-01-01 14:00"), 13, 17) is True
    assert in_session(pd.Timestamp("2024-01-01 13:00"), 13, 17) is True  # inclusivo no início


def test_in_session_fora():
    """Hora fora da janela."""
    assert in_session(pd.Timestamp("2024-01-01 17:00"), 13, 17) is False  # exclusivo no fim
    assert in_session(pd.Timestamp("2024-01-01 09:00"), 13, 17) is False


def test_in_session_cruza_meia_noite():
    """Janela 22-6 cruzando a meia-noite."""
    assert in_session(pd.Timestamp("2024-01-01 23:00"), 22, 6) is True
    assert in_session(pd.Timestamp("2024-01-01 03:00"), 22, 6) is True
    assert in_session(pd.Timestamp("2024-01-01 12:00"), 22, 6) is False


def test_in_session_desativado():
    """start == end -> filtro desativado (sempre True)."""
    assert in_session(pd.Timestamp("2024-01-01 00:00"), 0, 0) is True
    assert in_session(pd.Timestamp("2024-01-01 15:00"), 10, 10) is True


# ---------------------------------------------------------------------------
# Testes dos indicadores (tamanho e robustez)
# ---------------------------------------------------------------------------

def test_indicators_alinhados_e_tamanho():
    """Indicadores devem retornar séries do tamanho do índice de entrada."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = _ohlc_from_close(100 + np.linspace(0, 10, n), idx, spread=0.05)

    e = ind.ema(df["close"], 20)
    a = ind.atr(df["high"], df["low"], df["close"], 14)
    ax = ind.adx(df["high"], df["low"], df["close"], 14)
    macd_line, signal_line = ind.macd(df["close"])

    for s in (e, a, ax, macd_line, signal_line):
        assert len(s) == n
        assert s.index.equals(idx)


def test_indicators_poucos_dados_nao_explodem():
    """Com poucos dados, indicadores não devem levantar exceção."""
    idx = pd.date_range("2024-01-01", periods=3, freq="h")
    df = _ohlc_from_close(np.array([100.0, 101.0, 100.5]), idx, spread=0.05)

    assert len(ind.ema(df["close"], 20)) == 3
    assert len(ind.atr(df["high"], df["low"], df["close"], 14)) == 3
    assert len(ind.adx(df["high"], df["low"], df["close"], 14)) == 3
    ml, sl = ind.macd(df["close"])
    assert len(ml) == 3 and len(sl) == 3


def test_atr_positivo():
    """ATR deve ser não-negativo onde definido."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = _ohlc_from_close(100 + np.linspace(0, 5, n), idx, spread=0.1)
    a = ind.atr(df["high"], df["low"], df["close"], 14).dropna()
    assert (a >= 0).all()


def test_adx_entre_0_e_100():
    """ADX deve ficar no intervalo [0, 100] onde definido."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = _ohlc_from_close(100 + np.linspace(0, 20, n), idx, spread=0.05)
    ax = ind.adx(df["high"], df["low"], df["close"], 14).dropna()
    assert ((ax >= 0) & (ax <= 100)).all()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
