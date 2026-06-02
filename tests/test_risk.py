"""Testes das travas de risco e do sizing por ATR (smarttrader/risk.py).

Rodar: pytest tests/test_risk.py
"""

from datetime import datetime

import pytest

from smarttrader.risk import RiskManager, calculate_lot


# ---------------------------------------------------------------------------
# calculate_lot
# ---------------------------------------------------------------------------
def test_calculate_lot_caso_normal():
    """balance 10000, risco 1% -> 100$; perda/lote = (0.0020/0.00001)*1 = 200$.
    lote = 100/200 = 0.5."""
    lote = calculate_lot(
        balance=10_000.0,
        risk_pct=1.0,
        sl_distance_price=0.0020,
        tick_value=1.0,
        tick_size=0.00001,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
    )
    assert lote == 0.5


def test_calculate_lot_divisao_por_zero_retorna_zero():
    # tick_size = 0 -> divisão por zero -> 0.0
    assert (
        calculate_lot(10_000, 1.0, 0.0020, 1.0, 0.0, 0.01, 100.0, 0.01) == 0.0
    )
    # sl_distance = 0 -> stop inexistente -> 0.0
    assert (
        calculate_lot(10_000, 1.0, 0.0, 1.0, 0.00001, 0.01, 100.0, 0.01) == 0.0
    )
    # balance <= 0 -> 0.0
    assert (
        calculate_lot(0, 1.0, 0.0020, 1.0, 0.00001, 0.01, 100.0, 0.01) == 0.0
    )
    # tick_value <= 0 -> 0.0
    assert (
        calculate_lot(10_000, 1.0, 0.0020, 0.0, 0.00001, 0.01, 100.0, 0.01) == 0.0
    )


def test_calculate_lot_clamp_maximo():
    """Risco enorme deve ser limitado ao max_lot."""
    lote = calculate_lot(
        balance=1_000_000.0,
        risk_pct=50.0,
        sl_distance_price=0.0001,
        tick_value=1.0,
        tick_size=0.00001,
        min_lot=0.01,
        max_lot=2.0,
        lot_step=0.01,
    )
    assert lote == 2.0


def test_calculate_lot_clamp_minimo():
    """Risco minúsculo -> lote bruto < min_lot -> clamp pra min_lot."""
    lote = calculate_lot(
        balance=100.0,
        risk_pct=0.1,
        sl_distance_price=0.0050,
        tick_value=1.0,
        tick_size=0.00001,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
    )
    # risco$ = 0.10; perda/lote = (0.0050/0.00001)*1 = 500; bruto = 0.0002 -> < min
    assert lote == 0.01


def test_calculate_lot_arredonda_para_baixo_ao_step():
    """lote bruto 0.57 com step 0.1 -> arredonda para baixo -> 0.5."""
    # risco$ = 57; perda/lote = (0.0010/0.00001)*1 = 100; bruto = 0.57
    lote = calculate_lot(
        balance=5_700.0,
        risk_pct=1.0,
        sl_distance_price=0.0010,
        tick_value=1.0,
        tick_size=0.00001,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.1,
    )
    assert lote == 0.5


# ---------------------------------------------------------------------------
# RiskManager — helper de construção
# ---------------------------------------------------------------------------
def _rm():
    return RiskManager(
        max_daily_loss_pct=5.0,
        max_drawdown_pct=15.0,
        max_consec_losses=4,
        max_open_trades=1,
    )


def test_can_open_trade_ok():
    rm = _rm()
    rm.update_equity(10_000)
    ok, motivo = rm.can_open_trade(equity=10_000, balance=10_000, open_positions=0)
    assert ok is True
    assert motivo == "ok"


def test_bloqueio_por_max_open_trades():
    rm = _rm()
    rm.update_equity(10_000)
    ok, motivo = rm.can_open_trade(equity=10_000, balance=10_000, open_positions=1)
    assert ok is False
    assert "trades abertos" in motivo.lower()


def test_bloqueio_por_perda_diaria():
    rm = _rm()
    rm.update_equity(10_000)
    # Limite diário = 5% de 10000 = 500. Perde 500 -> bloqueia.
    rm.register_close(-500.0)
    ok, motivo = rm.can_open_trade(equity=9_500, balance=10_000, open_positions=0)
    assert ok is False
    assert "diária" in motivo.lower()


def test_bloqueio_por_drawdown_global():
    rm = _rm()
    # Pico em 10000; equity cai para 8500 -> dd = 15% -> bloqueia (>=).
    rm.update_equity(10_000)
    ok, motivo = rm.can_open_trade(equity=8_500, balance=10_000, open_positions=0)
    assert ok is False
    assert "drawdown" in motivo.lower()


def test_bloqueio_por_perdas_consecutivas():
    rm = _rm()
    rm.update_equity(10_000)
    # 4 perdas pequenas (não estouram a diária de 500): 4x -50 = -200.
    for _ in range(4):
        rm.register_close(-50.0)
    ok, motivo = rm.can_open_trade(equity=9_800, balance=10_000, open_positions=0)
    assert ok is False
    assert "consecutivas" in motivo.lower()


def test_lucro_zera_perdas_consecutivas():
    rm = _rm()
    rm.update_equity(10_000)
    rm.register_close(-50.0)
    rm.register_close(-50.0)
    assert rm.consec_losses == 2
    rm.register_close(+30.0)  # lucro zera o contador
    assert rm.consec_losses == 0
    ok, _ = rm.can_open_trade(equity=9_930, balance=10_000, open_positions=0)
    assert ok is True


def test_profit_zero_nao_mexe_contador():
    rm = _rm()
    rm.register_close(-50.0)
    rm.register_close(0.0)  # scratch: não incrementa nem zera
    assert rm.consec_losses == 1


def test_update_equity_move_o_pico():
    rm = _rm()
    rm.update_equity(10_000)
    assert rm.equity_peak == 10_000
    rm.update_equity(12_000)  # sobe -> pico acompanha
    assert rm.equity_peak == 12_000
    rm.update_equity(9_000)  # cai -> pico NÃO desce
    assert rm.equity_peak == 12_000
    # Agora o drawdown é medido a partir de 12000.
    # 12000 -> 10199 = 15.0%+ -> bloqueia.
    ok, motivo = rm.can_open_trade(equity=10_100, balance=12_000, open_positions=0)
    assert ok is False
    assert "drawdown" in motivo.lower()


def test_reset_ao_virar_o_dia():
    rm = _rm()
    rm.update_equity(10_000)
    dia1 = datetime(2026, 6, 2, 14, 0, 0)
    dia2 = datetime(2026, 6, 3, 9, 0, 0)

    # No dia 1: estoura perda diária e perdas consecutivas.
    for _ in range(4):
        rm.register_close(-150.0)  # total -600 (> 500) e 4 perdas
    ok, _ = rm.can_open_trade(
        equity=9_400, balance=10_000, open_positions=0, now=dia1
    )
    assert ok is False

    # No dia 2: PnL diário e contador de perdas resetam -> volta a operar.
    ok, motivo = rm.can_open_trade(
        equity=9_400, balance=10_000, open_positions=0, now=dia2
    )
    assert ok is True
    assert motivo == "ok"
    assert rm.daily_pnl == 0.0
    assert rm.consec_losses == 0


def test_drawdown_nao_reseta_ao_virar_o_dia():
    """O pico de equity é global e não deve sumir na virada do dia."""
    rm = _rm()
    rm.update_equity(10_000)
    dia2 = datetime(2026, 6, 3, 9, 0, 0)
    # Vira o dia (chama roll via can_open_trade); pico continua 10000.
    rm.can_open_trade(equity=10_000, balance=10_000, open_positions=0, now=dia2)
    assert rm.equity_peak == 10_000


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
