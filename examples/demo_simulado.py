"""DEMO — prova que a IA e o BOT funcionam, SEM precisar do MetaTrader 5.

Usa um MT5 SIMULADO (FakeMT5) no lugar do terminal real. Roda em qualquer PC
com Python + pandas/numpy. Para o teste com o MT5 de verdade, veja
docs/INSTALACAO_MT5.md (precisa de Windows + conta demo).

    python examples/demo_simulado.py
"""
import numpy as np
import pandas as pd

from smarttrader.config import Config
from smarttrader.news_ai import NewsBiasEngine, Bias
from smarttrader.news_mapper import detect_themes, bias_for_symbol
from smarttrader.risk import RiskManager
from smarttrader.trader import Trader


# ===========================================================================
# PARTE 1 — A IA interpretando uma notícia e decidindo direção
# ===========================================================================
def testar_ia():
    print("=" * 70)
    print(" PARTE 1 — IA: 'crise no petróleo' -> direção por ativo")
    print("=" * 70)
    manchetes = [
        "Oil prices spike after OPEC supply cut amid Middle East war escalation",
        "Crude surges as conflict threatens supply; investors flee to safe havens",
    ]
    for m in manchetes:
        print("  notícia:", m)

    temas = detect_themes(manchetes)
    print("\n  Temas detectados:")
    for t in temas:
        print(f"    - {t.theme:10s} sentimento={t.sentiment:+d} força={t.strength:.2f}")

    print("\n  Direção deduzida:")
    for sym in ("USOIL", "XAUUSD", "USDCAD"):
        b, conf, rat = bias_for_symbol(sym, temas)
        lado = {1: "COMPRA", -1: "VENDA", 0: "NEUTRO"}[b]
        print(f"    - {sym}: {lado} (conf {conf:.2f}) — {rat}")


# ===========================================================================
# PARTE 2 — O bot completo (MT5 simulado): decide e "abre" ordem
# ===========================================================================
def _uptrend(n, freq):
    """Tendência de alta REALISTA (acelerando) — dispara o sinal de compra."""
    idx = pd.date_range("2024-01-01", periods=n, freq=freq)
    incr = 0.02 + 0.0004 * np.arange(n)
    close = 100.0 + np.cumsum(incr) + np.random.default_rng(3).normal(0, 0.05, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + 0.05
    low = np.minimum(open_, close) - 0.05
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


class FakeMT5:
    """MT5 falso: registra a ordem em vez de enviar a um terminal real."""
    def __init__(self):
        self.ordens = []

    def get_rates(self, s, tf, c):
        return _uptrend(250, "D") if str(tf).upper().startswith("D") else _uptrend(c, "h")

    def symbol_info(self, s):
        return {"tick_value": 1.0, "tick_size": 0.0001, "point": 0.0001, "digits": 5,
                "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "spread": 10}

    def account_info(self):
        return {"balance": 10000.0, "equity": 10000.0, "margin_free": 10000.0, "currency": "USD"}

    def positions(self, symbol=None, magic=None):
        return []

    def open_trade(self, s, d, lot, sl, tp, magic, comment="ST"):
        lado = "COMPRA" if d == 1 else "VENDA"
        self.ordens.append(1)
        print(f"      >>> ORDEM ENVIADA AO MT5(sim): {lado} {s} lote={lot:.2f} SL={sl:.5f} TP={tp:.5f}")
        return {"sucesso": True, "retcode": 0, "comment": "ok", "ticket": 777}

    def modify_sl(self, *a, **k): return True
    def close_partial(self, *a, **k): return True
    def shutdown(self): pass


def _cfg(use_ai):
    return Config(
        mt5_login=0, mt5_password="x", mt5_server="Demo", mt5_path="",
        symbols=["EURUSD"], timeframe="H1", htf_timeframe="D1", magic=1,
        dry_run=False, use_ai=use_ai, risk_percent=1.0, atr_sl_mult=1.8, tp_r_multiple=1.0,
        partial_close_pct=50, breakeven_buffer_atr=0.2, trailing_atr_mult=2.5,
        max_open_trades=1, max_daily_loss_pct=5.0, max_drawdown_pct=15.0, max_consec_losses=4,
        use_session_filter=False, session_start_hour=0, session_end_hour=0,
    )


def testar_bot():
    print("\n" + "=" * 70)
    print(" PARTE 2 — BOT completo (MT5 simulado, tendência de alta)")
    print("=" * 70)

    print("\n  [A] Só técnica (use_ai=False):")
    c = FakeMT5(); Trader(_cfg(False), c, NewsBiasEngine(), RiskManager(5, 15, 4, 1)).run_once()
    print("      =>", "ABRIU ordem OK" if c.ordens else "não operou")

    print("\n  [B] Modo A — IA diz COMPRA e técnica confirma:")
    c = FakeMT5()
    Trader(_cfg(True), c, NewsBiasEngine(override_bias=Bias("EURUSD", 1, 0.8)),
           RiskManager(5, 15, 4, 1)).run_once()
    print("      =>", "ABRIU ordem OK" if c.ordens else "não operou")

    print("\n  [C] Modo A — IA diz VENDA, técnica é de ALTA (deve vetar):")
    c = FakeMT5()
    Trader(_cfg(True), c, NewsBiasEngine(override_bias=Bias("EURUSD", -1, 0.8)),
           RiskManager(5, 15, 4, 1)).run_once()
    print("      =>", "VETOU corretamente OK" if not c.ordens else "abriu (ERRADO)")


if __name__ == "__main__":
    testar_ia()
    testar_bot()
    print("\n" + "=" * 70)
    print(" Tudo exercitado SEM terminal real. Para o MT5 de verdade:")
    print(" veja docs/INSTALACAO_MT5.md (Windows + conta demo).")
    print("=" * 70)
