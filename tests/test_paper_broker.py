"""Testes do PaperBroker (corretora simulada) — offline, sem yfinance.

Controlamos o preço via ``mark()`` e validamos abertura, liquidação por SL/TP,
fechamento parcial e o P&L/saldo.
"""
from __future__ import annotations

from smarttrader.paper_broker import PaperBroker


def _broker(tmp_path):
    return PaperBroker(balance=10_000.0, state_path=str(tmp_path / "paper.json"))


def test_compra_atinge_tp_da_lucro(tmp_path):
    b = _broker(tmp_path)
    b.mark("EURUSD", 1.10)                       # define preço atual
    r = b.open_trade("EURUSD", 1, 1.0, sl=1.09, tp=1.12, magic=1)
    assert r["sucesso"]
    b.mark("EURUSD", 1.12)                       # toca o TP
    assert b.positions("EURUSD") == []          # posição fechada
    assert b.balance > 10_000.0                 # lucro
    assert b.history[-1]["motivo"] == "TP"


def test_compra_atinge_sl_da_prejuizo(tmp_path):
    b = _broker(tmp_path)
    b.mark("EURUSD", 1.10)
    b.open_trade("EURUSD", 1, 1.0, sl=1.09, tp=1.12, magic=1)
    b.mark("EURUSD", 1.089)                      # fura o SL
    assert b.positions("EURUSD") == []
    assert b.balance < 10_000.0
    assert b.history[-1]["motivo"] == "SL"


def test_venda_atinge_tp(tmp_path):
    b = _broker(tmp_path)
    b.mark("USDJPY", 150.0)
    b.open_trade("USDJPY", -1, 1.0, sl=151.0, tp=148.0, magic=1)
    b.mark("USDJPY", 148.0)                      # TP de venda (preço caiu)
    assert b.positions("USDJPY") == []
    assert b.balance > 10_000.0


def test_sem_stop_recusa(tmp_path):
    b = _broker(tmp_path)
    b.mark("EURUSD", 1.10)
    r = b.open_trade("EURUSD", 1, 1.0, sl=0, tp=1.12, magic=1)
    assert r["sucesso"] is False


def test_fechamento_parcial(tmp_path):
    b = _broker(tmp_path)
    b.mark("EURUSD", 1.10)
    b.open_trade("EURUSD", 1, 1.0, sl=1.09, tp=1.20, magic=1)
    b.mark("EURUSD", 1.11)                       # em lucro, sem tocar tp
    assert b.close_partial(1, 0.5) is True
    pos = b.positions("EURUSD")[0]
    assert abs(pos["volume"] - 0.5) < 1e-9       # metade fechada
    assert b.balance > 10_000.0                  # parcial deu lucro


def test_account_info_equity_reflete_flutuante(tmp_path):
    b = _broker(tmp_path)
    b.mark("EURUSD", 1.10)
    b.open_trade("EURUSD", 1, 1.0, sl=1.09, tp=1.50, magic=1)
    b.mark("EURUSD", 1.11)                       # +100 pips flutuando
    acc = b.account_info()
    assert acc["equity"] > acc["balance"]        # lucro flutuante aparece no equity


def test_persistencia(tmp_path):
    path = str(tmp_path / "paper.json")
    b = PaperBroker(balance=5_000.0, state_path=path)
    b.mark("EURUSD", 1.10)
    b.open_trade("EURUSD", 1, 1.0, sl=1.09, tp=1.12, magic=1)
    b.shutdown()
    b2 = PaperBroker(state_path=path)            # recarrega do disco
    assert len(b2.positions()) == 1
    assert b2.balance == 5_000.0
