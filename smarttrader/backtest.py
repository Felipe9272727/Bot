"""Backtest offline da estratégia técnica (sem MT5, sem dinheiro).

Valida a SmartTrader v2 em dados históricos candle a candle, SEM look-ahead e
COM custos (spread/comissão em pips) — porque backtest sem custo é ilusão
(ver docs/MESA_REDONDA.md). Usa risco fixo por trade (R-múltiplos): cada trade
arrisca uma fração do saldo.

PARIDADE COM O TRADER REAL (smarttrader/trader.py :: _manage_positions):
este backtest NÃO usa mais uma saída simples (TP único). Ele replica a gestão
real de posição, candle a candle:

  - Entrada no CLOSE do candle de sinal; SL = atr_sl_mult * ATR.
  - PARCIAL em +1R: fecha ``partial_close_pct``% da posição realizando +1R
    nessa fração e move o stop para BREAKEVEN + ``breakeven_buffer_atr`` * ATR.
  - TRAILING (Chandelier) no restante: para compra, stop sobe para
    ``max_recente - trailing_atr_mult*ATR``; para venda, espelhado. Só move a
    favor. A posição fecha quando o preço toca esse stop.
  - Custo (``cost_pips``) aplicado na ENTRADA e em CADA saída (a parcial conta
    como uma saída, então custa).

Simplificações honestas (documentadas aqui e nos comentários do código):
  - Fila/preenchimento no CLOSE do candle (não no próximo open); sem slippage
    variável — o custo é fixo em pips por perna.
  - Quando SL e TP/trailing caem no MESMO candle, assumimos o STOP primeiro
    (conservador), pois não temos dados intra-candle para saber a ordem real.
  - ATR usado na gestão é o ATR DA ENTRADA (congelado), espelhando o efeito de
    um R fixo definido na abertura; o trader real recalcula a cada candle, mas
    isso evita look-ahead e mantém o R-múltiplo coerente por trade.

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
    partial_close_pct: float = 50.0,
    breakeven_buffer_atr: float = 0.2,
    trailing_atr_mult: float = 2.5,
) -> dict:
    """Simula a estratégia técnica (sem IA) candle a candle, COM a gestão real.

    Uma posição por vez. Entra quando ``strategy_direction`` != 0 (no CLOSE do
    candle de sinal); SL = ``atr_sl_mult`` * ATR. A SAÍDA replica o trader real
    (``trader._manage_positions``): parcial em +1R, breakeven + buffer, e
    trailing Chandelier por ATR no restante. Ver docstring do módulo para as
    simplificações honestas (fila no close, sem slippage variável, stop antes do
    alvo no mesmo candle).

    Convenção de PnL em R: 1R é a distância ``atr_sl_mult*ATR`` definida na
    entrada. A fração parcial (``partial_close_pct``%) realiza +1R; o restante é
    liquidado pelo trailing/breakeven, podendo dar de ~-1R (raro, antes da
    parcial) até vários R. O custo de fricção (``cost_pips``) é debitado em R na
    entrada e em CADA saída (a parcial é uma saída).

    Parâmetros novos (com defaults idênticos ao trader/config) preservam a
    compatibilidade com as chamadas existentes (assinatura posicional/kwargs).

    Retorna métricas com as MESMAS chaves de sempre (trades, win_rate,
    profit_factor, expectancy_r, return_pct, max_drawdown_pct, final_balance) e
    chaves extras informativas (avg_win_r, avg_loss_r, partials).
    """
    p = params or StratParams()
    if df_htf is None:
        # Constrói o HTF (diário) a partir do exec, se não for fornecido.
        df_htf = df_exec.resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()

    warmup = max(p.ema_trend, p.macd_slow, p.adx_period) + 5
    cost_price = cost_pips * point
    partial_frac = max(0.0, min(1.0, partial_close_pct / 100.0))

    balance = initial_balance
    equity_curve = [balance]
    trades: list[dict] = []
    n_partials = 0

    # --- estado da posição aberta ---
    in_pos = False
    direction = 0
    entry = sl = 0.0
    r_dist = 0.0            # tamanho de 1R em preço (atr_sl_mult*ATR), congelado na entrada
    atr_entry = 0.0        # ATR da entrada (usado para breakeven/trailing — espelha R fixo)
    risk_money = 0.0       # $ que representa 1R deste trade
    partial_done = False
    remaining_frac = 1.0   # fração da posição ainda aberta (1.0 = cheia)
    extreme = 0.0          # máxima (compra) / mínima (venda) recente p/ Chandelier
    entry_cost_r = 0.0     # custo de fricção da ENTRADA (em R), cobrado na 1ª saída

    idx = df_exec.index
    high = df_exec["high"].values
    low = df_exec["low"].values
    close = df_exec["close"].values

    def _book(r_value: float) -> None:
        """Contabiliza um fechamento (parcial ou final) já em R líquido."""
        nonlocal balance
        money = r_value * risk_money
        balance += money
        trades.append({"r": r_value, "money": money})
        equity_curve.append(balance)

    for i in range(warmup, len(df_exec)):
        # --- gerenciar posição aberta (candle i, sem look-ahead) ---
        if in_pos:
            # custo de fricção em R por PERNA de SAÍDA (parcial/final).
            custo_perna_r = (cost_price / r_dist) if r_dist > 0 else 0.0
            # O custo da ENTRADA (entry_cost_r) é cobrado UMA vez, na primeira
            # saída deste trade — assim ele entra no PnL por-trade (e nas
            # métricas), em vez de virar um ponto fantasma na equity.

            if direction == 1:
                # 1) STOP primeiro (conservador): toca o SL atual?
                if low[i] <= sl:
                    # R bruto desta fração em relação à entrada
                    r_bruto = (sl - entry) / r_dist if r_dist > 0 else 0.0
                    _book(remaining_frac * (r_bruto - custo_perna_r) - entry_cost_r)
                    in_pos = False
                    continue
                # 2) PARCIAL em +1R (ainda não feita)?
                if not partial_done and high[i] >= entry + r_dist:
                    if partial_frac > 0.0:
                        # realiza +1R na fração parcial, menos custos (saída+entrada)
                        _book(partial_frac * (1.0 - custo_perna_r) - entry_cost_r)
                        entry_cost_r = 0.0    # já cobrado
                        n_partials += 1
                        remaining_frac -= partial_frac
                    partial_done = True
                    # move stop p/ breakeven + buffer (cobre spread)
                    sl = entry + breakeven_buffer_atr * atr_entry
                    extreme = high[i]
                # 3) TRAILING Chandelier (só após a parcial)
                if partial_done and trailing_atr_mult > 0:
                    extreme = max(extreme, high[i])
                    novo_sl = extreme - trailing_atr_mult * atr_entry
                    if novo_sl > sl:          # só move a favor
                        sl = novo_sl
            else:  # venda (espelhado)
                if high[i] >= sl:
                    r_bruto = (entry - sl) / r_dist if r_dist > 0 else 0.0
                    _book(remaining_frac * (r_bruto - custo_perna_r) - entry_cost_r)
                    in_pos = False
                    continue
                if not partial_done and low[i] <= entry - r_dist:
                    if partial_frac > 0.0:
                        _book(partial_frac * (1.0 - custo_perna_r) - entry_cost_r)
                        entry_cost_r = 0.0
                        n_partials += 1
                        remaining_frac -= partial_frac
                    partial_done = True
                    sl = entry - breakeven_buffer_atr * atr_entry
                    extreme = low[i]
                if partial_done and trailing_atr_mult > 0:
                    extreme = min(extreme, low[i])
                    novo_sl = extreme + trailing_atr_mult * atr_entry
                    if novo_sl < sl:          # só move a favor
                        sl = novo_sl

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
                    atr_entry = atr
                    r_dist = atr_sl_mult * atr
                    sl = entry - r_dist if d == 1 else entry + r_dist
                    risk_money = balance * risk_pct / 100.0
                    direction = d
                    in_pos = True
                    partial_done = False
                    remaining_frac = 1.0
                    extreme = entry
                    # custo da ENTRADA (em R) — cobrado na 1ª saída deste trade.
                    entry_cost_r = (cost_price / r_dist) if r_dist > 0 else 0.0

    extra = {"partials": n_partials}
    return _metrics(trades, equity_curve, initial_balance, balance, extra)


def _metrics(trades, equity_curve, initial_balance, final_balance,
             extra: dict | None = None) -> dict:
    """Calcula as métricas do backtest a partir dos trades e da curva de equity.

    ``extra`` (opcional) carrega chaves informativas adicionais (ex.: contagem
    de parciais) que são mescladas SEM remover as chaves do contrato original.
    """
    extra = extra or {}
    n = len(trades)
    if n == 0:
        base = {
            "trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy_r": 0.0, "return_pct": 0.0, "max_drawdown_pct": 0.0,
            "final_balance": float(final_balance),
            "avg_win_r": 0.0, "avg_loss_r": 0.0,
        }
        base.update(extra)
        return base
    rs = np.array([t["r"] for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]
    gross_win = float(np.sum([t["money"] for t in trades if t["money"] > 0]))
    gross_loss = float(abs(np.sum([t["money"] for t in trades if t["money"] < 0])))

    eq = np.array(equity_curve)
    pico = np.maximum.accumulate(eq)
    dd = (pico - eq) / pico
    max_dd = float(np.max(dd) * 100.0)

    base = {
        "trades": n,
        "win_rate": float(len(wins) / n * 100.0),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy_r": float(np.mean(rs)),
        "return_pct": float((final_balance - initial_balance) / initial_balance * 100.0),
        "max_drawdown_pct": max_dd,
        "final_balance": float(final_balance),
        "avg_win_r": float(np.mean(wins)) if len(wins) else 0.0,
        "avg_loss_r": float(np.mean(losses)) if len(losses) else 0.0,
    }
    base.update(extra)
    return base


def walk_forward(
    df_exec: pd.DataFrame,
    df_htf: pd.DataFrame | None = None,
    params: StratParams | None = None,
    n_splits: int = 4,
    **kw,
) -> list[dict]:
    """Validação fora-de-amostra deslizante: roda ``run_backtest`` por janela.

    Divide ``df_exec`` em ``n_splits`` janelas sequenciais (não sobrepostas) e
    roda um backtest independente em cada uma, retornando a lista de métricas
    por janela. É o teste anti-overfitting do docs/ESTRATEGIA.md: a borda só é
    crível se as métricas (expectância, profit factor) forem CONSISTENTES entre
    janelas.

    ⚠️ Leitura anti-overfitting: se o parâmetro/resultado "ótimo" PULA muito de
    uma janela para outra (ex.: lucrativa numa, desastre na seguinte), isso é
    sinal de SEM borda real — provavelmente curve-fitting/ruído, não vantagem.
    Consistência > pico de performance numa única janela.

    O HTF é fatiado por tempo para acompanhar cada janela; se ``df_htf`` for
    None, cada janela reconstrói o seu (diário) a partir do próprio recorte.
    Os ``**kw`` (risk_pct, atr_sl_mult, cost_pips, partial_close_pct, ...) são
    repassados intactos ao ``run_backtest``.
    """
    if n_splits < 1:
        raise ValueError("n_splits deve ser >= 1")

    n = len(df_exec)
    bordas = np.linspace(0, n, n_splits + 1, dtype=int)
    resultados: list[dict] = []
    for k in range(n_splits):
        ini, fim = int(bordas[k]), int(bordas[k + 1])
        janela = df_exec.iloc[ini:fim]
        htf_janela = None
        if df_htf is not None and len(janela):
            htf_janela = df_htf[
                (df_htf.index >= janela.index[0]) & (df_htf.index <= janela.index[-1])
            ]
        m = run_backtest(janela, htf_janela, params, **kw)
        m["split"] = k
        resultados.append(m)
    return resultados


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
    metrics = run_backtest(df, risk_pct=1.0, atr_sl_mult=1.8, tp_r=1.0, cost_pips=1.0)
    print_report(metrics)

    # Validação fora-de-amostra deslizante (anti-overfitting).
    print("\nWalk-forward (janelas fora-de-amostra) — consistência > pico:\n")
    janelas = walk_forward(df, n_splits=4, risk_pct=1.0, atr_sl_mult=1.8,
                           tp_r=1.0, cost_pips=1.0)
    print(f"  {'janela':>6} {'trades':>7} {'win%':>7} {'PF':>7} {'exp.R':>8}")
    for w in janelas:
        pf = w["profit_factor"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"  {w['split']:>6} {w['trades']:>7} {w['win_rate']:>6.1f}% "
              f"{pf_s:>7} {w['expectancy_r']:>+8.3f}")
    print("\n  Se as métricas pulam muito entre janelas, NÃO há borda confiável.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
