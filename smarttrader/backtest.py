"""Backtest offline da estratégia técnica (sem MT5, sem dinheiro).

Valida a SmartTrader v2 em dados históricos candle a candle, SEM look-ahead e
COM custos (spread/comissão em pips) — porque backtest sem custo é ilusão
(ver docs/MESA_REDONDA.md). Usa risco fixo por trade (R-múltiplos): cada trade
arrisca uma fração do saldo; o resultado é +TP_R (vitória) ou -1R (derrota),
menos o custo de fricção.

Rode um exemplo com dados sintéticos:

    python -m smarttrader.backtest

⚠️ Backtest bom NÃO é promessa de lucro. Serve para REPROVAR estratégias ruins
e medir robustez (profit factor, drawdown), exigindo validação fora-de-amostra.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from .strategy import StratParams, strategy_direction

log = logging.getLogger("smarttrader.backtest")


# ---------------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------------
def load_csv(path: str) -> pd.DataFrame:
    """Lê um CSV OHLC com índice datetime.

    Espera colunas (case-insensitive): time/date, open, high, low, close.
    """
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    time_col = next((c for c in ("time", "date", "datetime") if c in df.columns), None)
    if time_col is None:
        raise ValueError("CSV precisa de uma coluna de tempo (time/date/datetime).")
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.set_index(time_col).sort_index()
    faltando = {"open", "high", "low", "close"} - set(df.columns)
    if faltando:
        raise ValueError(f"CSV sem colunas OHLC: {faltando}")
    return df[["open", "high", "low", "close"]]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def run_backtest(
    df_exec: pd.DataFrame,
    df_htf: pd.DataFrame | None = None,
    params: StratParams | None = None,
    risk_pct: float = 1.0,
    atr_sl_mult: float = 1.8,
    tp_r: float = 1.0,
    cost_pips: float = 1.0,
    point: float = 0.0001,
    initial_balance: float = 10_000.0,
) -> dict:
    """Simula a estratégia técnica (sem IA) candle a candle.

    Uma posição por vez. Entra quando ``strategy_direction`` != 0; sai no
    primeiro toque de SL (-1R) ou TP (+tp_r R). Se SL e TP caem no mesmo candle,
    assume SL (conservador). Custo de fricção (spread+comissão) entra como
    cost_pips em CADA trade (entrada+saída).

    Retorna métricas: nº trades, win rate, profit factor, expectância (em R),
    retorno total %, max drawdown %.
    """
    p = params or StratParams()
    if df_htf is None:
        # Constrói o HTF (diário) a partir do exec, se não for fornecido.
        df_htf = df_exec.resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()

    warmup = max(p.ema_trend, p.macd_slow, p.adx_period) + 5
    cost_price = cost_pips * point

    balance = initial_balance
    equity_curve = [balance]
    trades: list[dict] = []

    in_pos = False
    direction = 0
    entry = sl = tp = 0.0
    risk_money = 0.0

    idx = df_exec.index
    high = df_exec["high"].values
    low = df_exec["low"].values
    close = df_exec["close"].values

    for i in range(warmup, len(df_exec)):
        # --- gerenciar posição aberta (checa SL/TP no candle i) ---
        if in_pos:
            hit_sl = low[i] <= sl if direction == 1 else high[i] >= sl
            hit_tp = high[i] >= tp if direction == 1 else low[i] <= tp
            resultado_r = None
            if hit_sl and hit_tp:
                resultado_r = -1.0          # conservador: assume SL primeiro
            elif hit_sl:
                resultado_r = -1.0
            elif hit_tp:
                resultado_r = tp_r
            if resultado_r is not None:
                # custo de fricção em R (entrada + saída)
                sl_dist = abs(entry - sl)
                custo_r = (2 * cost_price / sl_dist) if sl_dist > 0 else 0.0
                pnl_r = resultado_r - custo_r
                pnl_money = pnl_r * risk_money
                balance += pnl_money
                trades.append({"r": pnl_r, "money": pnl_money})
                equity_curve.append(balance)
                in_pos = False

        # --- procurar nova entrada (sem posição aberta) ---
        if not in_pos:
            sub_exec = df_exec.iloc[: i + 1]
            sub_htf = df_htf[df_htf.index <= idx[i]]
            d = strategy_direction(sub_exec, sub_htf, p)
            if d != 0:
                atr = ind.atr(sub_exec["high"], sub_exec["low"],
                              sub_exec["close"], p.atr_period).iloc[-1]
                if atr and atr > 0:
                    entry = close[i]
                    sl_dist = atr_sl_mult * atr
                    if d == 1:
                        sl, tp = entry - sl_dist, entry + tp_r * sl_dist
                    else:
                        sl, tp = entry + sl_dist, entry - tp_r * sl_dist
                    risk_money = balance * risk_pct / 100.0
                    direction = d
                    in_pos = True

    return _metrics(trades, equity_curve, initial_balance, balance)


def _metrics(trades, equity_curve, initial_balance, final_balance) -> dict:
    """Calcula as métricas do backtest a partir dos trades e da curva de equity."""
    n = len(trades)
    if n == 0:
        return {
            "trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy_r": 0.0, "return_pct": 0.0, "max_drawdown_pct": 0.0,
            "final_balance": final_balance,
        }
    rs = np.array([t["r"] for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]
    gross_win = float(np.sum([t["money"] for t in trades if t["money"] > 0]))
    gross_loss = float(abs(np.sum([t["money"] for t in trades if t["money"] < 0])))

    eq = np.array(equity_curve)
    pico = np.maximum.accumulate(eq)
    dd = (pico - eq) / pico
    max_dd = float(np.max(dd) * 100.0)

    return {
        "trades": n,
        "win_rate": float(len(wins) / n * 100.0),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy_r": float(np.mean(rs)),
        "return_pct": float((final_balance - initial_balance) / initial_balance * 100.0),
        "max_drawdown_pct": max_dd,
        "final_balance": float(final_balance),
    }


def print_report(m: dict) -> None:
    """Imprime o relatório do backtest de forma legível."""
    print("=" * 48)
    print("  RELATÓRIO DE BACKTEST — SmartTrader v2")
    print("=" * 48)
    print(f"  Trades............: {m['trades']}")
    print(f"  Taxa de acerto....: {m['win_rate']:.1f}%")
    pf = m["profit_factor"]
    print(f"  Profit factor.....: {'∞' if pf == float('inf') else f'{pf:.2f}'}")
    print(f"  Expectância.......: {m['expectancy_r']:+.3f} R / trade")
    print(f"  Retorno total.....: {m['return_pct']:+.2f}%")
    print(f"  Drawdown máximo...: {m['max_drawdown_pct']:.2f}%")
    print(f"  Saldo final.......: {m['final_balance']:.2f}")
    print("=" * 48)
    print("  ⚠️  Backtest NÃO é promessa de lucro. Valide fora-de-amostra,")
    print("      com custos reais e amostra grande antes de qualquer demo.")
    print("=" * 48)


# ---------------------------------------------------------------------------
# Dados sintéticos para um exemplo executável
# ---------------------------------------------------------------------------
def _synthetic_data(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    """Gera uma série H1 com tendências e pullbacks (mistura de regimes)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    # tendências alternadas com ruído (regimes)
    drift = np.zeros(n)
    bloco = 400
    for k in range(0, n, bloco):
        sinal = rng.choice([-1, 1]) * rng.uniform(0.01, 0.05)
        drift[k:k + bloco] = sinal
    ruido = rng.normal(0, 0.15, n)
    close = 100.0 + np.cumsum(drift + ruido)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.05, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.05, n))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    print("Rodando backtest de exemplo com dados sintéticos...\n")
    df = _synthetic_data()
    metrics = run_backtest(df, risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.5, cost_pips=1.0)
    print_report(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
