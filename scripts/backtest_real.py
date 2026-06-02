"""Backtest da SmartTrader v2 em DADOS REAIS de mercado (via yfinance).

Este é o teste honesto: o "simulador hiper-realista" é o próprio mercado que já
aconteceu. Baixa preço real, roda a estratégia com custos e mostra as métricas
+ walk-forward (fora-de-amostra). Funciona local ou no Google Colab.

    pip install yfinance pandas numpy
    python scripts/backtest_real.py

⚠️ Resultado real NÃO é promessa de futuro. Serve para ver se a estratégia tem
alguma borda em mercado de verdade, em vários ativos/regimes.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("Instale o yfinance:  pip install yfinance")
    sys.exit(1)

from smarttrader.backtest import print_report, run_backtest, walk_forward
from smarttrader.strategy import StratParams

# Ativos variados (forex, ouro, índice, ação) p/ testar regimes diferentes.
SIMBOLOS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "Ouro (XAU)": "GC=F",
    "S&P500": "^GSPC",
}


def baixar(ticker: str, period="15y", interval="1d") -> pd.DataFrame:
    """Baixa OHLC real e normaliza para colunas open/high/low/close."""
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        return pd.DataFrame()
    # yfinance recente retorna colunas MultiIndex (Price, Ticker).
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    df = df[["open", "high", "low", "close"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def rodar(nome: str, ticker: str) -> None:
    df = baixar(ticker)
    if len(df) < 300:
        print(f"\n### {nome}: dados insuficientes ({len(df)} linhas) — pulando.")
        return

    # Execução = diário; HTF = semanal (viés de tendência maior).
    htf = df.resample("1W").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    # Custo realista ~2 bps por perna (spread+comissão de ativo líquido).
    preco_medio = float(df["close"].mean())
    cost_price = 0.0002 * preco_medio  # 0,02% do preço

    p = StratParams()
    m = run_backtest(
        df, htf, p,
        risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.0,
        cost_pips=cost_price, point=1.0,   # cost_price = cost_pips*point
    )
    print(f"\n{'#'*60}\n### {nome}  ({ticker}) — {len(df)} candles diários reais")
    print(f"### período: {df.index[0].date()} a {df.index[-1].date()}")
    print('#'*60)
    print_report(m)

    # Walk-forward (consistência entre janelas fora-de-amostra)
    janelas = walk_forward(df, htf, p, n_splits=4,
                           risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.0,
                           cost_pips=cost_price, point=1.0)
    print("  Walk-forward (4 janelas fora-de-amostra):")
    print(f"  {'janela':>7} {'trades':>7} {'win%':>7} {'PF':>7} {'exp.R':>8}")
    for w in janelas:
        pf = w["profit_factor"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"  {w['split']:>7} {w['trades']:>7} {w['win_rate']:>6.1f}% "
              f"{pf_s:>7} {w['expectancy_r']:>+8.3f}")


def main():
    print("Baixando DADOS REAIS e testando a SmartTrader v2 (pode levar ~1 min)...")
    for nome, ticker in SIMBOLOS.items():
        try:
            rodar(nome, ticker)
        except Exception as e:
            print(f"\n### {nome}: erro — {e!r}")
    print("\n" + "=" * 60)
    print(" Leia: consistência entre janelas e entre ATIVOS importa mais que")
    print(" o pico de um só. Se varia muito, a 'borda' é frágil/sorte.")
    print("=" * 60)


if __name__ == "__main__":
    main()
