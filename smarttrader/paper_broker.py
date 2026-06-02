"""PaperBroker — corretora SIMULADA (paper trading) com preço REAL ao vivo.

É um substituto "plug-and-play" do ``MT5Connector``: implementa os MESMOS
métodos (get_rates, symbol_info, account_info, positions, open_trade,
modify_sl, close_partial), então o ``Trader`` roda EXATAMENTE igual — só que
com dinheiro fake e sem precisar do MetaTrader 5 / Windows.

- Preço real via ``yfinance`` (ou uma ``price_fn`` injetável para testes).
- Conta virtual (saldo, posições, P&L) persistida em JSON, então sobrevive
  entre execuções.
- As ordens são "executadas" no simulador; SL/TP são liquidados quando o preço
  os toca (a cada atualização de preço).

⚠️ Paper trading NÃO é dinheiro real e nem o demo oficial do broker (que tem
spread/slippage reais). É o teste do LOOP COMPLETO de decisão+execução.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("smarttrader.paper")

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


# Mapeia o símbolo do projeto -> ticker do Yahoo Finance.
YF_MAP = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCAD": "USDCAD=X", "XAUUSD": "GC=F", "USOIL": "CL=F",
    "SPX": "^GSPC", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
}

# Info sintética por símbolo (tick_size/tick_value internamente consistentes,
# usados tanto no sizing quanto no P&L — então o risco % faz sentido).
_SYMBOL_INFO = {
    "USDJPY": {"tick_size": 0.01, "tick_value": 1.0},
    "XAUUSD": {"tick_size": 0.01, "tick_value": 1.0},
    "USOIL":  {"tick_size": 0.01, "tick_value": 1.0},
    "SPX":    {"tick_size": 0.1,  "tick_value": 1.0},
    "BTCUSD": {"tick_size": 1.0,  "tick_value": 1.0},
    "ETHUSD": {"tick_size": 0.1,  "tick_value": 1.0},
}
_DEFAULT_INFO = {"tick_size": 0.0001, "tick_value": 1.0}

# Mapa de timeframe -> (interval, period) do yfinance.
_TF_MAP = {
    "M15": ("15m", "5d"), "M30": ("30m", "20d"),
    "H1": ("1h", "60d"), "H4": ("1h", "120d"),
    "D1": ("1d", "2y"), "W1": ("1wk", "5y"),
}


class PaperBroker:
    """Corretora simulada com a mesma interface do MT5Connector."""

    def __init__(self, balance: float = 10_000.0,
                 state_path: str = "paper_state.json",
                 price_fn=None):
        """price_fn(symbol, timeframe, count) -> DataFrame OHLC (para testes;
        se None, usa yfinance)."""
        self.state_path = state_path
        self.price_fn = price_fn
        self._last_price: dict[str, float] = {}
        self._load(balance)

    # ---- conexão (no-op; existe só para casar a interface) ----
    def connect(self, *a, **k) -> bool:
        log.info("PaperBroker conectado (simulado). Saldo=%.2f", self.balance)
        return True

    def shutdown(self):
        self._save()

    # ---- persistência ----
    def _load(self, balance):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                st = json.load(f)
            self.balance = st.get("balance", balance)
            self.positions_list = st.get("positions", [])
            self.next_ticket = st.get("next_ticket", 1)
            self.history = st.get("history", [])
        else:
            self.balance = balance
            self.positions_list = []
            self.next_ticket = 1
            self.history = []

    def _save(self):
        with open(self.state_path, "w") as f:
            json.dump({"balance": self.balance, "positions": self.positions_list,
                       "next_ticket": self.next_ticket, "history": self.history},
                      f, indent=2)

    # ---- dados de mercado ----
    def get_rates(self, symbol, timeframe, count):
        if self.price_fn is not None:
            df = self.price_fn(symbol, timeframe, count)
        else:
            df = self._yf_rates(symbol, timeframe, count)
        if df is not None and len(df):
            self.mark(symbol, float(df["close"].iloc[-1]))  # liquida SL/TP
        return df

    def _yf_rates(self, symbol, timeframe, count):
        if yf is None or pd is None:
            raise RuntimeError("yfinance/pandas necessários para preço ao vivo.")
        ticker = YF_MAP.get(symbol.upper(), symbol)
        interval, period = _TF_MAP.get(str(timeframe).upper(), ("1h", "60d"))
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            raise RuntimeError(f"Sem cotação para {symbol} ({ticker}).")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={c: c.lower() for c in df.columns})
        return df[["open", "high", "low", "close"]].dropna().tail(count)

    def symbol_info(self, symbol) -> dict:
        info = dict(_SYMBOL_INFO.get(symbol.upper(), _DEFAULT_INFO))
        info.update({"point": info["tick_size"], "digits": 5,
                     "volume_min": 0.01, "volume_max": 100.0,
                     "volume_step": 0.01, "spread": 0})
        return info

    def account_info(self) -> dict:
        equity = self.balance + self._floating_pnl()
        return {"balance": round(self.balance, 2), "equity": round(equity, 2),
                "margin_free": round(equity, 2), "currency": "USD"}

    # ---- posições ----
    def positions(self, symbol=None, magic=None) -> list:
        out = []
        for p in self.positions_list:
            if symbol is not None and p["symbol"] != symbol:
                continue
            if magic is not None and p["magic"] != magic:
                continue
            out.append(dict(p))
        return out

    def open_trade(self, symbol, direction, lot, sl, tp, magic,
                   comment="paper") -> dict:
        if sl is None or sl <= 0:
            return {"sucesso": False, "retcode": None,
                    "comment": "SL obrigatório", "ticket": None}
        price = self._last_price.get(symbol)
        if price is None:
            return {"sucesso": False, "retcode": None,
                    "comment": "sem preço (chame get_rates antes)", "ticket": None}
        ticket = self.next_ticket
        self.next_ticket += 1
        self.positions_list.append({
            "ticket": ticket, "symbol": symbol,
            "type": 0 if direction == 1 else 1, "volume": round(lot, 2),
            "price_open": price, "sl": sl, "tp": tp, "profit": 0.0,
            "magic": magic, "opened_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        log.info("[PAPER] ABRE %s %s lote=%.2f @ %.5f sl=%.5f tp=%.5f",
                 "COMPRA" if direction == 1 else "VENDA", symbol, lot, price, sl, tp)
        return {"sucesso": True, "retcode": 0, "comment": "ok", "ticket": ticket}

    def modify_sl(self, ticket, sl, tp=None) -> bool:
        for p in self.positions_list:
            if p["ticket"] == ticket:
                p["sl"] = sl
                if tp is not None:
                    p["tp"] = tp
                self._save()
                return True
        return False

    def close_partial(self, ticket, volume) -> bool:
        for p in self.positions_list:
            if p["ticket"] == ticket:
                price = self._last_price.get(p["symbol"], p["price_open"])
                vol = min(volume, p["volume"])
                self._book(p, price, vol, motivo="parcial")
                p["volume"] = round(p["volume"] - vol, 2)
                if p["volume"] <= 0:
                    self.positions_list.remove(p)
                self._save()
                return True
        return False

    # ---- núcleo da simulação: liquidar SL/TP e contabilizar P&L ----
    def mark(self, symbol, price: float):
        """Atualiza o preço e liquida posições que tocaram SL ou TP."""
        self._last_price[symbol] = price
        for p in list(self.positions_list):
            if p["symbol"] != symbol:
                continue
            is_buy = p["type"] == 0
            sl, tp = p["sl"], p["tp"]
            # SL primeiro (conservador)
            if is_buy and price <= sl or (not is_buy and price >= sl):
                self._book(p, sl, p["volume"], motivo="SL")
                self.positions_list.remove(p)
            elif tp and (is_buy and price >= tp or (not is_buy and price <= tp)):
                self._book(p, tp, p["volume"], motivo="TP")
                self.positions_list.remove(p)
        self._save()

    def _pnl(self, p, exit_price, volume) -> float:
        info = self.symbol_info(p["symbol"])
        d = 1 if p["type"] == 0 else -1
        diff = (exit_price - p["price_open"]) * d
        return (diff / info["tick_size"]) * info["tick_value"] * volume

    def _floating_pnl(self) -> float:
        total = 0.0
        for p in self.positions_list:
            price = self._last_price.get(p["symbol"])
            if price is not None:
                total += self._pnl(p, price, p["volume"])
        return total

    def _book(self, p, exit_price, volume, motivo):
        pnl = self._pnl(p, exit_price, volume)
        self.balance += pnl
        self.history.append({
            "ticket": p["ticket"], "symbol": p["symbol"],
            "type": "COMPRA" if p["type"] == 0 else "VENDA",
            "volume": volume, "entry": p["price_open"], "exit": exit_price,
            "pnl": round(pnl, 2), "motivo": motivo,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
        log.info("[PAPER] FECHA(%s) %s lote=%.2f @ %.5f  P&L=%.2f  saldo=%.2f",
                 motivo, p["symbol"], volume, exit_price, pnl, self.balance)

    # ---- relatório ----
    def report(self) -> dict:
        fechados = self.history
        wins = [t for t in fechados if t["pnl"] > 0]
        return {
            "saldo": round(self.balance, 2),
            "equity": self.account_info()["equity"],
            "posicoes_abertas": len(self.positions_list),
            "trades_fechados": len(fechados),
            "win_rate": round(len(wins) / len(fechados) * 100, 1) if fechados else 0.0,
            "pnl_total": round(sum(t["pnl"] for t in fechados), 2),
        }
