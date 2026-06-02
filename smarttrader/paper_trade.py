"""Roda o bot em PAPER TRADING (dinheiro fake, preço real ao vivo).

Usa o PaperBroker no lugar do MT5 — o ``Trader`` roda igual, mas simulado.
Funciona em qualquer máquina (inclusive Colab), sem MetaTrader 5 / Windows.

Exemplos:
    python -m smarttrader.paper_trade --once            # 1 ciclo, só técnica
    python -m smarttrader.paper_trade --once --ai       # 1 ciclo, IA ao vivo (Modo A)
    python -m smarttrader.paper_trade --poll 600        # laço a cada 10 min
    python -m smarttrader.paper_trade --reset           # zera a conta paper
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from .config import load_config
from .news_ai import NewsBiasEngine
from .paper_broker import PaperBroker
from .risk import RiskManager
from .trader import Trader

log = logging.getLogger("smarttrader.paper")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SmartTrader — paper trading (fake money, preço real)")
    ap.add_argument("--once", action="store_true", help="roda 1 ciclo e sai")
    ap.add_argument("--poll", type=int, default=300, help="intervalo do laço (s)")
    ap.add_argument("--balance", type=float, default=10_000.0, help="saldo inicial")
    ap.add_argument("--state", default="paper_state.json", help="arquivo de estado")
    ap.add_argument("--reset", action="store_true", help="zera a conta paper")
    ap.add_argument("--ai", action="store_true", help="liga a IA de notícias ao vivo (Modo A)")
    ap.add_argument("--model", default="", help="caminho do FinBERT (ex.: /content/drive/MyDrive/finbert_ft)")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if a.reset and os.path.exists(a.state):
        os.remove(a.state)
        log.info("Conta paper zerada (%s removido).", a.state)

    cfg = load_config()
    cfg.dry_run = False              # paper EXECUTA (no simulador)
    cfg.use_ai = a.ai
    cfg.use_session_filter = False   # paper: opera a qualquer hora p/ facilitar o teste

    broker = PaperBroker(balance=a.balance, state_path=a.state)
    broker.connect()
    news = NewsBiasEngine()
    risk = RiskManager(cfg.max_daily_loss_pct, cfg.max_drawdown_pct,
                       cfg.max_consec_losses, cfg.max_open_trades)
    if a.ai:
        # No Modo A a IA decide a direção pelas notícias AO VIVO.
        # Se houver caminho de modelo, carrega o SEU FinBERT para refinar a confiança.
        scorer = None
        model_path = a.model or os.environ.get("MODEL_PATH", "")
        if model_path:
            try:
                from .sentiment import FinBertSentiment
                scorer = FinBertSentiment(model_path)
                log.info("FinBERT carregado de %s (refina a confiança).", model_path)
            except Exception as exc:  # noqa: BLE001
                log.warning("Não carreguei o FinBERT (%r). Seguindo sem ele.", exc)
        news.get_bias = lambda s, _sc=scorer: news.bias_from_live_news(s, scorer=_sc)  # type: ignore[assignment]
        log.info("IA de notícias ao vivo LIGADA (Modo A)%s.",
                 " com seu FinBERT" if scorer else " (sem FinBERT)")

    trader = Trader(cfg, broker, news, risk)

    def ciclo():
        trader.run_once()
        print("📊 RELATÓRIO PAPER:", broker.report())

    log.info("Paper trading iniciado | símbolos=%s | IA=%s | saldo=%.2f",
             cfg.symbols, a.ai, broker.balance)
    try:
        if a.once:
            ciclo()
        else:
            while True:
                ciclo()
                time.sleep(a.poll)
    except KeyboardInterrupt:
        log.info("Encerrando (Ctrl+C).")
    finally:
        broker.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
