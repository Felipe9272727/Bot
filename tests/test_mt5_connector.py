"""Testes do MT5Connector com um pacote ``MetaTrader5`` FALSO.

O módulo real só roda no Windows. Aqui injetamos, via monkeypatch, um módulo
fake em ``smarttrader.mt5_connector.mt5`` com as constantes e funções que o
conector usa, devolvendo objetos fake. Assim testamos a lógica do conector
(montagem do request, regras de segurança, mapeamento de timeframe) sem MT5.
"""

from __future__ import annotations

import types

import pytest

import smarttrader.mt5_connector as conn_mod
from smarttrader.mt5_connector import MT5Connector, _map_timeframe, _ERRO_SEM_MT5


# ---------------------------------------------------------------------------
# Objetos fake (tick, info, result, position)
# ---------------------------------------------------------------------------
class _Obj:
    """Objeto genérico com atributos a partir de kwargs."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_mt5():
    """Constrói um módulo fake do MetaTrader5 com constantes e funções.

    As funções registram chamadas em ``mod._calls`` para inspeção nos testes.
    """
    mod = types.SimpleNamespace()

    # --- constantes ---
    mod.ORDER_TYPE_BUY = 0
    mod.ORDER_TYPE_SELL = 1
    mod.TRADE_ACTION_DEAL = 1
    mod.TRADE_ACTION_SLTP = 2
    mod.TRADE_RETCODE_DONE = 10009
    mod.TIMEFRAME_M1 = 1
    mod.TIMEFRAME_M5 = 5
    mod.TIMEFRAME_M15 = 15
    mod.TIMEFRAME_M30 = 30
    mod.TIMEFRAME_H1 = 16385
    mod.TIMEFRAME_H4 = 16388
    mod.TIMEFRAME_D1 = 16408
    mod.TIMEFRAME_W1 = 32769
    mod.TIMEFRAME_MN1 = 49153
    mod.ORDER_FILLING_FOK = 0
    mod.ORDER_FILLING_IOC = 1
    mod.ORDER_TIME_GTC = 0
    mod.POSITION_TYPE_BUY = 0

    # --- estado/registros ---
    mod._calls = {"order_send": []}
    mod._last_error = (0, "ok")

    # --- funções ---
    mod.last_error = lambda: mod._last_error

    def initialize(*a, **k):
        return True
    mod.initialize = initialize

    def login(*a, **k):
        return True
    mod.login = login

    mod.shutdown = lambda: None
    mod.symbol_select = lambda symbol, on: True

    # tick com ask/bid distintos para verificar buy@ask / sell@bid.
    mod.symbol_info_tick = lambda symbol: _Obj(ask=1.1010, bid=1.1000)

    # symbol_info com filling_mode=1 (FOK) e demais campos usados.
    mod.symbol_info = lambda symbol: _Obj(
        filling_mode=1,
        trade_tick_value=1.0, trade_tick_size=0.0001, point=0.0001, digits=5,
        volume_min=0.01, volume_max=100.0, volume_step=0.01, spread=1,
    )

    mod.account_info = lambda: _Obj(
        balance=10_000.0, equity=10_000.0, margin_free=10_000.0, currency="USD"
    )

    mod.positions_get = lambda *a, **k: ()

    def order_send(request):
        mod._calls["order_send"].append(request)
        return _Obj(retcode=mod.TRADE_RETCODE_DONE, comment="ok", order=12345)
    mod.order_send = order_send

    return mod


@pytest.fixture()
def fake_mt5(monkeypatch):
    """Injeta o mt5 fake e devolve um conector já 'conectado'."""
    mod = _fake_mt5()
    monkeypatch.setattr(conn_mod, "mt5", mod)
    return mod


def _conectado(fake_mt5):
    c = MT5Connector()
    assert c.connect(123, "senha", "Broker-Demo") is True
    return c


# ===========================================================================
# _map_timeframe
# ===========================================================================
def test_map_timeframe_h1_retorna_constante(fake_mt5):
    assert _map_timeframe("H1") == fake_mt5.TIMEFRAME_H1


def test_map_timeframe_d1_retorna_constante(fake_mt5):
    assert _map_timeframe("D1") == fake_mt5.TIMEFRAME_D1


def test_map_timeframe_int_repassa_direto(fake_mt5):
    assert _map_timeframe(16385) == 16385


def test_map_timeframe_desconhecido_cai_em_h1(fake_mt5):
    assert _map_timeframe("XYZ") == fake_mt5.TIMEFRAME_H1


# ===========================================================================
# open_trade
# ===========================================================================
def test_open_trade_recusa_sl_invalido_sem_order_send(fake_mt5):
    """sl<=0 -> recusa e NÃO chama order_send (regra de segurança)."""
    c = _conectado(fake_mt5)
    res = c.open_trade("EURUSD", 1, 0.10, 0.0, 1.1050, magic=777)
    assert res["sucesso"] is False
    assert "Stop Loss" in res["comment"]
    assert fake_mt5._calls["order_send"] == []  # nada enviado


def test_open_trade_compra_usa_ask_e_buy(fake_mt5):
    """COMPRA: type=BUY e price=ask; sucesso quando retcode==DONE."""
    c = _conectado(fake_mt5)
    res = c.open_trade("EURUSD", 1, 0.10, 1.0980, 1.1050, magic=777)
    assert res["sucesso"] is True
    assert res["retcode"] == fake_mt5.TRADE_RETCODE_DONE
    assert res["ticket"] == 12345
    req = fake_mt5._calls["order_send"][-1]
    assert req["type"] == fake_mt5.ORDER_TYPE_BUY
    assert req["price"] == 1.1010  # ask
    assert req["action"] == fake_mt5.TRADE_ACTION_DEAL
    assert req["sl"] == 1.0980


def test_open_trade_venda_usa_bid_e_sell(fake_mt5):
    """VENDA: type=SELL e price=bid."""
    c = _conectado(fake_mt5)
    res = c.open_trade("EURUSD", -1, 0.10, 1.1050, 1.0950, magic=777)
    assert res["sucesso"] is True
    req = fake_mt5._calls["order_send"][-1]
    assert req["type"] == fake_mt5.ORDER_TYPE_SELL
    assert req["price"] == 1.1000  # bid


def test_open_trade_direcao_invalida(fake_mt5):
    """Direção fora de {1,-1} -> recusa sem enviar ordem."""
    c = _conectado(fake_mt5)
    res = c.open_trade("EURUSD", 0, 0.10, 1.0980, 1.1050, magic=777)
    assert res["sucesso"] is False
    assert fake_mt5._calls["order_send"] == []


def test_open_trade_retcode_diferente_de_done_falha(fake_mt5):
    """Quando retcode != DONE -> sucesso=False (mas order_send foi chamado)."""
    fake_mt5.order_send = lambda request: _Obj(
        retcode=99999, comment="rejeitado", order=None
    )
    c = _conectado(fake_mt5)
    res = c.open_trade("EURUSD", 1, 0.10, 1.0980, 1.1050, magic=777)
    assert res["sucesso"] is False
    assert res["retcode"] == 99999


# ===========================================================================
# mt5 ausente (None) -> RuntimeError
# ===========================================================================
def test_connect_sem_mt5_levanta_runtimeerror(monkeypatch):
    monkeypatch.setattr(conn_mod, "mt5", None)
    c = MT5Connector()
    with pytest.raises(RuntimeError) as exc:
        c.connect(123, "x", "Broker")
    assert _ERRO_SEM_MT5 in str(exc.value)


def test_get_rates_sem_mt5_levanta_runtimeerror(monkeypatch):
    monkeypatch.setattr(conn_mod, "mt5", None)
    c = MT5Connector()
    with pytest.raises(RuntimeError) as exc:
        c.get_rates("EURUSD", "H1", 100)
    assert _ERRO_SEM_MT5 in str(exc.value)


def test_map_timeframe_sem_mt5_levanta_runtimeerror(monkeypatch):
    monkeypatch.setattr(conn_mod, "mt5", None)
    with pytest.raises(RuntimeError) as exc:
        _map_timeframe("H1")
    assert _ERRO_SEM_MT5 in str(exc.value)


# ===========================================================================
# Operações que exigem conexão antes de connect()
# ===========================================================================
def test_get_rates_sem_conexao_levanta_runtimeerror(fake_mt5):
    """mt5 disponível, mas sem connect() -> RuntimeError de 'não conectado'."""
    c = MT5Connector()
    with pytest.raises(RuntimeError) as exc:
        c.get_rates("EURUSD", "H1", 100)
    assert "não conectado" in str(exc.value)
