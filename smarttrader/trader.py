"""Laço principal do SmartTrader — a IA é a trader (Modo A).

Fluxo (por símbolo, a cada candle fechado):
  1. Gerencia posições abertas (parcial em 1R, breakeven, trailing por ATR).
  2. Decide direção: no Modo A a IA de notícias decide e a técnica CONFIRMA.
  3. Aplica travas de risco (RiskManager).
  4. Dimensiona o lote por ATR e executa (ou apenas LOGA, em DRY_RUN).

A função ``decide`` é pura (sem MT5) e é o coração testável da combinação
IA + técnica. O resto orquestra a conexão com o terminal MT5.

Segurança: padrão é conta DEMO + DRY_RUN. Toda ordem entra com Stop Loss.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

from . import indicators as ind
from .config import Config, load_config
from .mt5_connector import MT5Connector
from .news_ai import Bias, NewsBiasEngine
from .risk import RiskManager, calculate_lot
from .strategy import StratParams, in_session, strategy_direction

log = logging.getLogger("smarttrader.trader")


# ---------------------------------------------------------------------------
# Núcleo da decisão (PURO — testável sem MT5)
# ---------------------------------------------------------------------------
def decide(
    symbol: str,
    df_exec,
    df_htf,
    bias: Bias | None,
    use_ai: bool,
    p: StratParams,
) -> int:
    """Combina IA (direção) + estratégia técnica (confirmação) -> 1/-1/0.

    Modo A (use_ai=True): a IA é a trader.
      - Se o viés é neutro/blocked/stale -> 0 (não opera).
      - Só opera se a técnica CONFIRMAR a mesma direção do viés.
    Sem IA (use_ai=False): usa só a técnica (permite backtest sem notícias).
    """
    tech = strategy_direction(df_exec, df_htf, p)

    if not use_ai:
        return tech

    # Modo A: a IA decide a direção; a técnica precisa confirmar.
    if bias is None or bias.bias == 0 or bias.blocked or bias.stale:
        return 0
    if tech == bias.bias:
        return bias.bias
    return 0


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
class Trader:
    """Orquestra dados, decisão, risco e execução no MT5."""

    # quantos candles baixar (suficiente p/ EMA200 + folga)
    BARS = 500

    def __init__(
        self,
        config: Config,
        connector: MT5Connector,
        news_engine: NewsBiasEngine,
        risk_manager: RiskManager,
        params: StratParams | None = None,
    ) -> None:
        self.cfg = config
        self.conn = connector
        self.news = news_engine
        self.risk = risk_manager
        self.p = params or StratParams()
        # timestamp do último candle FECHADO já processado, por símbolo
        self._last_bar: dict[str, object] = {}

    # ------------------------------------------------------------------
    # Um ciclo
    # ------------------------------------------------------------------
    def run_once(self) -> None:
        """Roda um ciclo de decisão para todos os símbolos configurados."""
        for symbol in self.cfg.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as exc:  # fail-safe: um símbolo não derruba o resto
                log.exception("Erro processando %s: %r", symbol, exc)

    def _process_symbol(self, symbol: str) -> None:
        # Baixa candles (posição 0 = candle em formação -> descartamos a última linha)
        df_full = self.conn.get_rates(symbol, self.cfg.timeframe, self.BARS)
        df_htf_full = self.conn.get_rates(symbol, self.cfg.htf_timeframe, 250)
        df_exec = df_full.iloc[:-1]   # só candles FECHADOS
        df_htf = df_htf_full.iloc[:-1]
        if len(df_exec) < self.p.ema_trend + 5:
            log.warning("%s: poucos candles (%d) para EMA%d.",
                        symbol, len(df_exec), self.p.ema_trend)
            return

        # 1) Gerencia posições abertas (parcial / breakeven / trailing)
        self._manage_positions(symbol, df_exec)

        # Detecta barra nova (evita reprocessar o mesmo candle fechado)
        last_bar_time = df_exec.index[-1]
        if self._last_bar.get(symbol) == last_bar_time:
            return
        self._last_bar[symbol] = last_bar_time

        # 2) Filtro de sessão (hora do servidor ~ timestamp do candle)
        if self.cfg.use_session_filter and not in_session(
            last_bar_time, self.cfg.session_start_hour, self.cfg.session_end_hour
        ):
            log.debug("%s: fora da sessão de operação.", symbol)
            return

        # Uma posição por símbolo
        if self.conn.positions(symbol=symbol, magic=self.cfg.magic):
            return

        # 3) Travas de risco (globais)
        acct = self.conn.account_info()
        self.risk.update_equity(acct["equity"])
        abertas = len(self.conn.positions(magic=self.cfg.magic))
        pode, motivo = self.risk.can_open_trade(
            equity=acct["equity"], balance=acct["balance"], open_positions=abertas
        )
        if not pode:
            log.info("%s: trava de risco bloqueou entrada: %s", symbol, motivo)
            return

        # Direção: Modo A (IA decide + técnica confirma) ou só técnica
        bias = self.news.get_bias(symbol) if self.cfg.use_ai else None
        direction = decide(symbol, df_exec, df_htf, bias, self.cfg.use_ai, self.p)
        if direction == 0:
            return

        # 4) Stop por ATR e dimensionamento
        atr = ind.atr(df_exec["high"], df_exec["low"], df_exec["close"],
                      self.p.atr_period).iloc[-1]
        if atr is None or atr != atr or atr <= 0:  # NaN ou inválido
            log.warning("%s: ATR inválido (%s).", symbol, atr)
            return

        sl_dist = self.cfg.atr_sl_mult * atr
        info = self.conn.symbol_info(symbol)
        lot = calculate_lot(
            balance=acct["balance"],
            risk_pct=self.cfg.risk_percent,
            sl_distance_price=sl_dist,
            tick_value=info["tick_value"],
            tick_size=info["tick_size"],
            min_lot=info["volume_min"],
            max_lot=info["volume_max"],
            lot_step=info["volume_step"],
        )
        if lot <= 0:
            log.warning("%s: lote calculado 0 — não opera.", symbol)
            return

        entry = float(df_exec["close"].iloc[-1])  # aproximação do preço atual
        if direction == 1:
            sl = entry - sl_dist
            tp = entry + self.cfg.tp_r_multiple * sl_dist
        else:
            sl = entry + sl_dist
            tp = entry - self.cfg.tp_r_multiple * sl_dist

        lado = "COMPRA" if direction == 1 else "VENDA"
        if self.cfg.dry_run:
            log.info(
                "[DRY-RUN] %s %s lote=%.2f entry~%.5f sl=%.5f tp=%.5f (ATR=%.5f)%s",
                lado, symbol, lot, entry, sl, tp, atr,
                "" if not self.cfg.use_ai else f" | viés IA={bias.bias} conf={bias.confidence:.2f}",
            )
            return

        res = self.conn.open_trade(symbol, direction, lot, sl, tp, self.cfg.magic)
        if res.get("sucesso"):
            log.info("%s %s ABERTA: lote=%.2f sl=%.5f tp=%.5f ticket=%s",
                     lado, symbol, lot, sl, tp, res.get("ticket"))
        else:
            log.error("%s %s FALHOU: %s", lado, symbol, res.get("comment"))

    # ------------------------------------------------------------------
    # Gerenciamento de posições abertas
    # ------------------------------------------------------------------
    def _manage_positions(self, symbol: str, df_exec) -> None:
        """Parcial em 1R, breakeven + buffer, e trailing Chandelier por ATR."""
        if self.cfg.dry_run:
            return  # em DRY-RUN não há ordens reais para gerenciar

        posicoes = self.conn.positions(symbol=symbol, magic=self.cfg.magic)
        if not posicoes:
            return

        atr = ind.atr(df_exec["high"], df_exec["low"], df_exec["close"],
                      self.p.atr_period).iloc[-1]
        if atr is None or atr != atr or atr <= 0:
            return
        price = float(df_exec["close"].iloc[-1])
        r = self.cfg.atr_sl_mult * atr           # tamanho de 1R (aprox.)
        buffer = self.cfg.breakeven_buffer_atr * atr

        for pos in posicoes:
            is_buy = pos["type"] == 0
            entry = pos["price_open"]
            sl = pos["sl"]
            vol = pos["volume"]
            ticket = pos["ticket"]

            # parcial já feita? -> SL já em breakeven (ou melhor)
            if is_buy:
                partial_done = sl >= entry > 0
                profit_dist = price - entry
            else:
                partial_done = 0 < sl <= entry
                profit_dist = entry - price

            # Atingiu 1R e ainda não fez parcial -> fecha parcial + breakeven
            if not partial_done and profit_dist >= r:
                vol_partial = round(vol * self.cfg.partial_close_pct / 100.0, 2)
                if vol_partial > 0 and (vol - vol_partial) >= 0:
                    if self.conn.close_partial(ticket, vol_partial):
                        log.info("%s: parcial de %.2f lote em 1R (ticket %s).",
                                 symbol, vol_partial, ticket)
                novo_sl = entry + buffer if is_buy else entry - buffer
                if self.conn.modify_sl(ticket, novo_sl):
                    log.info("%s: SL movido para breakeven (%.5f).", symbol, novo_sl)
                continue

            # Trailing Chandelier (só depois da parcial)
            if partial_done and self.cfg.trailing_atr_mult > 0:
                if is_buy:
                    novo_sl = price - self.cfg.trailing_atr_mult * atr
                    if novo_sl > sl:
                        self.conn.modify_sl(ticket, novo_sl)
                else:
                    novo_sl = price + self.cfg.trailing_atr_mult * atr
                    if sl == 0 or novo_sl < sl:
                        self.conn.modify_sl(ticket, novo_sl)

    # ------------------------------------------------------------------
    # Laço 24h
    # ------------------------------------------------------------------
    def run_forever(self, poll_seconds: int = 30) -> None:
        """Roda continuamente; um erro de ciclo não derruba o processo."""
        log.info("SmartTrader iniciado (dry_run=%s, use_ai=%s, símbolos=%s).",
                 self.cfg.dry_run, self.cfg.use_ai, self.cfg.symbols)
        try:
            while True:
                try:
                    self.run_once()
                except Exception as exc:  # fail-safe global
                    log.exception("Erro no ciclo: %r", exc)
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            log.info("Encerrando (Ctrl+C).")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SmartTrader — bot MT5 (a IA é a trader)")
    parser.add_argument("--once", action="store_true",
                        help="roda um único ciclo e sai (útil para teste)")
    parser.add_argument("--poll", type=int, default=30,
                        help="intervalo do laço em segundos (run_forever)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config()

    conn = MT5Connector()
    # Precisamos de dados do terminal mesmo em DRY_RUN (só não enviamos ordens).
    if not conn.connect(cfg.mt5_login, cfg.mt5_password, cfg.mt5_server, cfg.mt5_path or None):
        log.error("Não foi possível conectar ao MT5. Verifique credenciais/terminal.")
        return 1

    news = NewsBiasEngine(news_api_key=cfg.news_api_key or None,
                          llm_api_key=cfg.llm_api_key or None)
    risk = RiskManager(
        max_daily_loss_pct=cfg.max_daily_loss_pct,
        max_drawdown_pct=cfg.max_drawdown_pct,
        max_consec_losses=cfg.max_consec_losses,
        max_open_trades=cfg.max_open_trades,
    )
    trader = Trader(cfg, conn, news, risk)

    try:
        if args.once:
            trader.run_once()
        else:
            trader.run_forever(poll_seconds=args.poll)
    finally:
        conn.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
