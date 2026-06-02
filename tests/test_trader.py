"""Testes do núcleo de decisão (trader.decide) e smoke test do backtest.

``decide`` é puro (não toca no MT5): monkeypatchamos ``strategy_direction``
para controlar o sinal técnico e validamos a lógica do Modo A.
"""

from __future__ import annotations

import smarttrader.trader as trader
from smarttrader.backtest import _synthetic_data, run_backtest
from smarttrader.news_ai import Bias
from smarttrader.strategy import StratParams

P = StratParams()


def _patch_tech(monkeypatch, value):
    """Faz strategy_direction (visto pelo trader) retornar `value`."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: value)


# ---------------------------------------------------------------------------
# decide() — sem IA
# ---------------------------------------------------------------------------
def test_decide_sem_ia_usa_tecnica(monkeypatch):
    _patch_tech(monkeypatch, 1)
    assert trader.decide("EURUSD", None, None, None, False, P) == 1
    _patch_tech(monkeypatch, -1)
    assert trader.decide("EURUSD", None, None, None, False, P) == -1
    _patch_tech(monkeypatch, 0)
    assert trader.decide("EURUSD", None, None, None, False, P) == 0


# ---------------------------------------------------------------------------
# decide() — Modo A (IA decide, técnica confirma)
# ---------------------------------------------------------------------------
def test_decide_ia_e_tecnica_concordam(monkeypatch):
    _patch_tech(monkeypatch, 1)
    bias = Bias("EURUSD", bias=1, confidence=0.7)
    assert trader.decide("EURUSD", None, None, bias, True, P) == 1


def test_decide_ia_e_tecnica_discordam(monkeypatch):
    _patch_tech(monkeypatch, -1)
    bias = Bias("EURUSD", bias=1, confidence=0.7)  # IA compra, técnica vende
    assert trader.decide("EURUSD", None, None, bias, True, P) == 0


def test_decide_ia_neutra_nao_opera(monkeypatch):
    _patch_tech(monkeypatch, 1)
    bias = Bias("EURUSD", bias=0, confidence=0.0)
    assert trader.decide("EURUSD", None, None, bias, True, P) == 0


def test_decide_ia_bloqueada_nao_opera(monkeypatch):
    _patch_tech(monkeypatch, 1)
    bias = Bias("EURUSD", bias=1, confidence=0.9, blocked=True)
    assert trader.decide("EURUSD", None, None, bias, True, P) == 0


def test_decide_ia_stale_nao_opera(monkeypatch):
    _patch_tech(monkeypatch, 1)
    bias = Bias("EURUSD", bias=1, confidence=0.9, stale=True)
    assert trader.decide("EURUSD", None, None, bias, True, P) == 0


def test_decide_ia_sem_bias_nao_opera(monkeypatch):
    _patch_tech(monkeypatch, 1)
    assert trader.decide("EURUSD", None, None, None, True, P) == 0


# ---------------------------------------------------------------------------
# backtest — smoke test
# ---------------------------------------------------------------------------
def test_backtest_roda_e_retorna_metricas():
    df = _synthetic_data(n=2000, seed=7)
    m = run_backtest(df, risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.5, cost_pips=1.0)
    # contrato das métricas
    for chave in ("trades", "win_rate", "profit_factor", "expectancy_r",
                  "return_pct", "max_drawdown_pct", "final_balance"):
        assert chave in m
    assert m["trades"] >= 0
    assert 0.0 <= m["win_rate"] <= 100.0
    assert 0.0 <= m["max_drawdown_pct"] <= 100.0


def test_backtest_sem_trades_nao_explode():
    # poucos dados -> sem trades -> métricas zeradas, sem erro
    df = _synthetic_data(n=300, seed=1)
    m = run_backtest(df)
    assert m["trades"] >= 0
