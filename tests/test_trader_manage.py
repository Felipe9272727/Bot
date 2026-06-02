"""Testes da classe ``Trader`` (_process_symbol e _manage_positions).

Não usamos o MT5 real: injetamos um ``FakeConnector`` 100% Python que registra
as chamadas (open_trade, modify_sl, close_partial) e devolve dados controlados
(candles sintéticos, info de símbolo/conta e posições configuráveis).

Estratégia de teste:
  * ``trader.strategy_direction`` é monkeypatchado para controlar o sinal técnico
    (com ``use_ai=False`` o ``decide`` repassa esse sinal direto);
  * o DataFrame OHLC é construído com variação suficiente para um ATR positivo;
  * o filtro de sessão é desligado para isolar a lógica que está sendo testada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import smarttrader.trader as trader
from smarttrader.config import Config
from smarttrader.news_ai import NewsBiasEngine
from smarttrader.risk import RiskManager
from smarttrader.strategy import StratParams


# ---------------------------------------------------------------------------
# FakeConnector — substituto Python puro do MT5Connector
# ---------------------------------------------------------------------------
class FakeConnector:
    """Conector falso: registra chamadas e devolve dados controlados.

    Não fala com o MT5; serve apenas para os testes do ``Trader``.
    """

    def __init__(self, rates=None, positions_list=None, account=None, info=None):
        # Dados controlados.
        self._rates = rates
        self._positions = positions_list or []
        self._account = account or {"balance": 10_000.0, "equity": 10_000.0,
                                    "margin_free": 10_000.0, "currency": "USD"}
        self._info = info or {
            "tick_value": 1.0,
            "tick_size": 0.0001,
            "point": 0.0001,
            "digits": 5,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "spread": 1,
        }
        # Registros das chamadas (para asserts).
        self.open_trade_calls = []
        self.modify_sl_calls = []
        self.close_partial_calls = []

    # --- dados de mercado ---
    def get_rates(self, symbol, timeframe, count):
        # Devolve sempre uma cópia do DataFrame sintético configurado.
        return self._rates.copy()

    def symbol_info(self, symbol):
        return dict(self._info)

    def account_info(self):
        return dict(self._account)

    # --- posições ---
    def positions(self, symbol=None, magic=None):
        # Devolve a lista controlada (já filtrada nos testes que precisam).
        return list(self._positions)

    # --- execução (apenas registra) ---
    def open_trade(self, symbol, direction, lot, sl, tp, magic, comment="SmartTrader"):
        self.open_trade_calls.append(
            {"symbol": symbol, "direction": direction, "lot": lot,
             "sl": sl, "tp": tp, "magic": magic}
        )
        return {"sucesso": True, "retcode": 10009, "comment": "ok", "ticket": 1}

    def modify_sl(self, ticket, sl, tp=None):
        self.modify_sl_calls.append({"ticket": ticket, "sl": sl, "tp": tp})
        return True

    def close_partial(self, ticket, volume):
        self.close_partial_calls.append({"ticket": ticket, "volume": volume})
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_df(n=260, base=1.1000, seed=1):
    """Cria um DataFrame OHLC sintético com índice datetime e ATR positivo.

    A variação (dente de serra) garante True Range > 0 em todas as barras.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    # Pequena tendência + ruído para manter high/low afastados (ATR > 0).
    drift = np.linspace(0, 0.0050, n)
    noise = rng.normal(0, 0.0003, n)
    close = base + drift + noise
    high = close + 0.0010
    low = close - 0.0010
    open_ = close - noise / 2
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "tick_volume": np.full(n, 100)},
        index=idx,
    )


def _make_config(**overrides):
    """Config com dry_run=False, use_ai=False e parâmetros conhecidos."""
    base = dict(
        mt5_login=0, mt5_password="", mt5_server="", mt5_path="",
        symbols=["EURUSD"], timeframe="H1", htf_timeframe="D1", magic=777,
        dry_run=False, use_ai=False,
        risk_percent=1.0, atr_sl_mult=2.0, tp_r_multiple=2.0,
        partial_close_pct=50.0, breakeven_buffer_atr=0.0, trailing_atr_mult=3.0,
        max_open_trades=1, max_daily_loss_pct=5.0, max_drawdown_pct=15.0,
        max_consec_losses=4,
        use_session_filter=False, session_start_hour=0, session_end_hour=0,
        news_api_key="", llm_api_key="",
    )
    base.update(overrides)
    return Config(**base)


def _make_trader(cfg, conn, params=None):
    """Monta um Trader real com o FakeConnector e dependências reais simples."""
    return trader.Trader(
        cfg, conn,
        NewsBiasEngine(),
        RiskManager(
            max_daily_loss_pct=cfg.max_daily_loss_pct,
            max_drawdown_pct=cfg.max_drawdown_pct,
            max_consec_losses=cfg.max_consec_losses,
            max_open_trades=cfg.max_open_trades,
        ),
        params or StratParams(),
    )


# ===========================================================================
# _process_symbol
# ===========================================================================
def test_process_symbol_setup_compra_valido_abre(monkeypatch):
    """Setup de COMPRA válido -> open_trade com direction=1, sl>0, tp>0, lote>0."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: 1)
    df = _make_df()
    conn = FakeConnector(rates=df)
    cfg = _make_config()
    t = _make_trader(cfg, conn)

    t._process_symbol("EURUSD")

    assert len(conn.open_trade_calls) == 1
    call = conn.open_trade_calls[0]
    assert call["direction"] == 1
    assert call["sl"] > 0
    assert call["tp"] > 0
    assert call["lot"] > 0
    # COMPRA: SL abaixo e TP acima do preço de entrada.
    assert call["sl"] < call["tp"]


def test_process_symbol_setup_venda_valido_abre(monkeypatch):
    """Setup de VENDA válido -> open_trade com direction=-1; SL acima, TP abaixo."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: -1)
    df = _make_df()
    conn = FakeConnector(rates=df)
    cfg = _make_config()
    t = _make_trader(cfg, conn)

    t._process_symbol("EURUSD")

    assert len(conn.open_trade_calls) == 1
    call = conn.open_trade_calls[0]
    assert call["direction"] == -1
    assert call["sl"] > 0 and call["tp"] > 0
    # VENDA: SL acima e TP abaixo do preço.
    assert call["sl"] > call["tp"]


def test_process_symbol_dry_run_nao_abre(monkeypatch):
    """Em DRY_RUN não chama open_trade (só logaria)."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: 1)
    df = _make_df()
    conn = FakeConnector(rates=df)
    cfg = _make_config(dry_run=True)
    t = _make_trader(cfg, conn)

    t._process_symbol("EURUSD")

    assert conn.open_trade_calls == []


def test_process_symbol_trava_risco_nao_abre(monkeypatch):
    """Trava de risco bloqueando -> não abre."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: 1)
    df = _make_df()
    conn = FakeConnector(rates=df)
    cfg = _make_config()
    t = _make_trader(cfg, conn)
    # Força o RiskManager a bloquear qualquer entrada.
    monkeypatch.setattr(t.risk, "can_open_trade",
                        lambda **k: (False, "bloqueado para teste"))

    t._process_symbol("EURUSD")

    assert conn.open_trade_calls == []


def test_process_symbol_posicao_existente_nao_abre(monkeypatch):
    """Já há posição no símbolo -> não abre nova."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: 1)
    df = _make_df()
    pos = [{"ticket": 1, "symbol": "EURUSD", "type": 0, "volume": 0.10,
            "price_open": 1.1000, "sl": 1.0980, "tp": 1.1040,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    cfg = _make_config()
    t = _make_trader(cfg, conn)

    t._process_symbol("EURUSD")

    assert conn.open_trade_calls == []


def test_process_symbol_direcao_zero_nao_abre(monkeypatch):
    """Sinal técnico 0 (sem setup) -> não abre."""
    monkeypatch.setattr(trader, "strategy_direction", lambda *a, **k: 0)
    df = _make_df()
    conn = FakeConnector(rates=df)
    cfg = _make_config()
    t = _make_trader(cfg, conn)

    t._process_symbol("EURUSD")

    assert conn.open_trade_calls == []


# ===========================================================================
# _manage_positions
# ===========================================================================
def _atr_e_price(df, cfg, p):
    """Calcula o ATR e o preço usados internamente pelo _manage_positions."""
    from smarttrader import indicators as ind
    df_exec = df.iloc[:-1]
    atr = ind.atr(df_exec["high"], df_exec["low"], df_exec["close"],
                  p.atr_period).iloc[-1]
    price = float(df_exec["close"].iloc[-1])
    return float(atr), price


def test_manage_compra_1r_faz_parcial_e_breakeven():
    """COMPRA que atingiu 1R: close_partial + modify_sl ~breakeven."""
    df = _make_df()
    cfg = _make_config(breakeven_buffer_atr=0.0)
    p = StratParams()
    atr, price = _atr_e_price(df, cfg, p)
    r = cfg.atr_sl_mult * atr

    # Entry tal que price - entry passa de 1R (folga p/ evitar borda de float);
    # SL abaixo do entry (parcial ainda não feita).
    entry = price - r * 1.001
    pos = [{"ticket": 10, "symbol": "EURUSD", "type": 0, "volume": 0.10,
            "price_open": entry, "sl": entry - r, "tp": entry + 2 * r,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    t = _make_trader(cfg, conn, p)

    t._manage_positions("EURUSD", df.iloc[:-1])

    # Parcial de 50% de 0.10 = 0.05
    assert len(conn.close_partial_calls) == 1
    assert conn.close_partial_calls[0]["ticket"] == 10
    assert abs(conn.close_partial_calls[0]["volume"] - 0.05) < 1e-9
    # SL movido para ~breakeven (buffer=0 -> exatamente o entry).
    assert len(conn.modify_sl_calls) == 1
    assert abs(conn.modify_sl_calls[0]["sl"] - entry) < 1e-9


def test_manage_compra_trailing_move_sl_a_favor():
    """COMPRA com parcial já feita (sl em breakeven): trailing sobe o SL."""
    df = _make_df()
    cfg = _make_config(trailing_atr_mult=3.0)
    p = StratParams()
    atr, price = _atr_e_price(df, cfg, p)

    # sl >= entry > 0 -> partial_done = True. Entry bem abaixo do preço para que
    # o trailing (price - trailing*atr) fique acima do sl atual.
    entry = price - 10 * atr
    sl_atual = entry  # breakeven
    pos = [{"ticket": 11, "symbol": "EURUSD", "type": 0, "volume": 0.05,
            "price_open": entry, "sl": sl_atual, "tp": entry + 100 * atr,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    t = _make_trader(cfg, conn, p)

    t._manage_positions("EURUSD", df.iloc[:-1])

    # Não faz parcial de novo; só trailing.
    assert conn.close_partial_calls == []
    assert len(conn.modify_sl_calls) == 1
    novo_sl = conn.modify_sl_calls[0]["sl"]
    esperado = price - cfg.trailing_atr_mult * atr
    assert abs(novo_sl - esperado) < 1e-9
    assert novo_sl > sl_atual  # moveu a favor (para cima)


def test_manage_venda_1r_faz_parcial_e_breakeven():
    """VENDA que atingiu 1R: close_partial + modify_sl ~breakeven (espelhado)."""
    df = _make_df()
    cfg = _make_config(breakeven_buffer_atr=0.0)
    p = StratParams()
    atr, price = _atr_e_price(df, cfg, p)
    r = cfg.atr_sl_mult * atr

    # VENDA: profit_dist = entry - price; passa de 1R com folga. SL acima.
    entry = price + r * 1.001
    pos = [{"ticket": 20, "symbol": "EURUSD", "type": 1, "volume": 0.10,
            "price_open": entry, "sl": entry + r, "tp": entry - 2 * r,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    t = _make_trader(cfg, conn, p)

    t._manage_positions("EURUSD", df.iloc[:-1])

    assert len(conn.close_partial_calls) == 1
    assert abs(conn.close_partial_calls[0]["volume"] - 0.05) < 1e-9
    assert len(conn.modify_sl_calls) == 1
    assert abs(conn.modify_sl_calls[0]["sl"] - entry) < 1e-9


def test_manage_venda_trailing_move_sl_a_favor():
    """VENDA com parcial já feita: trailing desce o SL a favor."""
    df = _make_df()
    cfg = _make_config(trailing_atr_mult=3.0)
    p = StratParams()
    atr, price = _atr_e_price(df, cfg, p)

    # VENDA com 0 < sl <= entry -> partial_done. Entry bem acima do preço.
    entry = price + 10 * atr
    sl_atual = entry  # breakeven
    pos = [{"ticket": 21, "symbol": "EURUSD", "type": 1, "volume": 0.05,
            "price_open": entry, "sl": sl_atual, "tp": entry - 100 * atr,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    t = _make_trader(cfg, conn, p)

    t._manage_positions("EURUSD", df.iloc[:-1])

    assert conn.close_partial_calls == []
    assert len(conn.modify_sl_calls) == 1
    novo_sl = conn.modify_sl_calls[0]["sl"]
    esperado = price + cfg.trailing_atr_mult * atr
    assert abs(novo_sl - esperado) < 1e-9
    assert novo_sl < sl_atual  # moveu a favor (para baixo)


def test_manage_dry_run_nao_faz_nada():
    """Em DRY_RUN o _manage_positions não toca em nada."""
    df = _make_df()
    cfg = _make_config(dry_run=True)
    p = StratParams()
    atr, price = _atr_e_price(df, cfg, p)
    r = cfg.atr_sl_mult * atr
    entry = price - r
    pos = [{"ticket": 30, "symbol": "EURUSD", "type": 0, "volume": 0.10,
            "price_open": entry, "sl": entry - r, "tp": entry + 2 * r,
            "profit": 0.0, "magic": 777}]
    conn = FakeConnector(rates=df, positions_list=pos)
    t = _make_trader(cfg, conn, p)

    t._manage_positions("EURUSD", df.iloc[:-1])

    assert conn.close_partial_calls == []
    assert conn.modify_sl_calls == []


def test_manage_sem_posicoes_nao_faz_nada():
    """Sem posições abertas, nada acontece."""
    df = _make_df()
    cfg = _make_config()
    conn = FakeConnector(rates=df, positions_list=[])
    t = _make_trader(cfg, conn)

    t._manage_positions("EURUSD", df.iloc[:-1])

    assert conn.close_partial_calls == []
    assert conn.modify_sl_calls == []
