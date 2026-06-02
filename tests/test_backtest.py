"""Testes do backtest com gestão real (paridade com trader._manage_positions).

Validam: (1) contrato de métricas em dados sintéticos; (2) a parcial em +1R é
de fato exercitada num cenário de alta forte (com expectância finita); (3) o
walk-forward devolve uma lista com ``n_splits`` dicionários de métricas.

Não tocam no MT5: tudo roda offline com pandas/numpy.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from smarttrader.backtest import _synthetic_data, run_backtest, walk_forward

CONTRATO = (
    "trades", "win_rate", "profit_factor", "expectancy_r",
    "return_pct", "max_drawdown_pct", "final_balance",
)


def _trend_data(n: int = 3000, drift: float = 0.05, seed: int = 3) -> pd.DataFrame:
    """Série H1 de ALTA forte e limpa (pouco ruído) — força confluência de compra."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    close = 100.0 + np.cumsum(np.full(n, drift) + rng.normal(0, 0.05, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.02, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.02, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close}, index=idx
    )


# ---------------------------------------------------------------------------
# 1) Contrato das métricas
# ---------------------------------------------------------------------------
def test_run_backtest_contrato_metricas():
    df = _synthetic_data(n=2000, seed=7)
    m = run_backtest(df, risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.0, cost_pips=1.0)

    for chave in CONTRATO:
        assert chave in m, f"chave de contrato ausente: {chave}"

    assert m["trades"] >= 0
    assert 0.0 <= m["win_rate"] <= 100.0
    assert 0.0 <= m["max_drawdown_pct"] <= 100.0
    # expectância e profit factor devem ser números (PF pode ser +inf se sem perdas)
    assert math.isfinite(m["expectancy_r"])
    assert m["profit_factor"] >= 0.0


def test_run_backtest_sem_trades_nao_explode():
    # poucos dados -> warmup engole tudo -> sem trades, métricas zeradas
    df = _synthetic_data(n=300, seed=1)
    m = run_backtest(df)
    assert m["trades"] >= 0
    for chave in CONTRATO:
        assert chave in m


# ---------------------------------------------------------------------------
# 2) A parcial em +1R é exercitada
# ---------------------------------------------------------------------------
def test_parcial_em_1r_exercitada_em_alta_forte():
    df = _trend_data(n=3000, drift=0.05, seed=3)
    m = run_backtest(df, risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.0,
                     cost_pips=1.0, partial_close_pct=50.0)

    assert m["trades"] > 0, "alta forte deveria gerar trades"
    # 'partials' é a chave extra que conta quantas parciais em +1R ocorreram
    assert m.get("partials", 0) > 0, "a parcial em +1R não foi exercitada"
    assert math.isfinite(m["expectancy_r"])
    # numa alta limpa, a gestão (parcial + trailing) deve ter expectância positiva
    assert m["expectancy_r"] > 0.0


def test_partial_close_pct_zero_nao_realiza_parcial():
    # com 0% de parcial, nenhum fechamento parcial deve ocorrer
    df = _trend_data(n=2500, drift=0.05, seed=5)
    m = run_backtest(df, partial_close_pct=0.0, tp_r=1.0, cost_pips=1.0)
    assert m.get("partials", 0) == 0


# ---------------------------------------------------------------------------
# 3) walk_forward
# ---------------------------------------------------------------------------
def test_walk_forward_retorna_n_splits():
    df = _synthetic_data(n=4000, seed=11)
    n_splits = 4
    janelas = walk_forward(df, n_splits=n_splits, risk_pct=1.0,
                           atr_sl_mult=1.8, tp_r=1.0, cost_pips=1.0)
    assert isinstance(janelas, list)
    assert len(janelas) == n_splits
    for k, w in enumerate(janelas):
        assert w["split"] == k
        for chave in CONTRATO:
            assert chave in w
        assert 0.0 <= w["win_rate"] <= 100.0
        assert w["trades"] >= 0


def test_walk_forward_n_splits_invalido():
    df = _synthetic_data(n=500, seed=2)
    try:
        walk_forward(df, n_splits=0)
    except ValueError:
        pass
    else:
        raise AssertionError("n_splits=0 deveria levantar ValueError")
