"""Gestão de risco do SmartTrader.

Dois componentes:

1. `calculate_lot` — sizing por ATR: traduz "arrisco X% do saldo" em volume
   (lotes), dado o tamanho do stop em preço e os parâmetros do símbolo.
2. `RiskManager` — as travas P0 da mesa redonda (docs/MESA_REDONDA.md):
   perda diária máxima, drawdown GLOBAL máximo, perdas consecutivas e máximo
   de trades abertos. Estas travas desligam/pausam o bot — são a borda real.
"""

from __future__ import annotations

import math
from datetime import date, datetime


# ---------------------------------------------------------------------------
# Sizing por ATR
# ---------------------------------------------------------------------------
def calculate_lot(
    balance: float,
    risk_pct: float,
    sl_distance_price: float,
    tick_value: float,
    tick_size: float,
    min_lot: float,
    max_lot: float,
    lot_step: float,
) -> float:
    """Calcula o volume (lotes) para arriscar `risk_pct`% do saldo.

    Fórmula:
      risco$            = balance * risk_pct / 100
      perda_por_lote$   = (sl_distance_price / tick_size) * tick_value
      lote_bruto        = risco$ / perda_por_lote$

    Em seguida normaliza ao `lot_step` (arredonda PARA BAIXO, nunca arrisca
    mais que o pedido) e faz clamp em [min_lot, max_lot].

    Proteções: qualquer entrada inválida (<= 0 onde não pode, ou divisão por
    zero) retorna 0.0 — "sem stop / sem dados, não abre".
    """
    # --- Proteções contra divisão por zero / valores inválidos ---
    if balance <= 0 or risk_pct <= 0:
        return 0.0
    if sl_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    if lot_step <= 0 or min_lot < 0 or max_lot <= 0:
        return 0.0

    # Dinheiro que estamos dispostos a perder neste trade.
    risco_dollar = balance * risk_pct / 100.0

    # Quanto perdemos por 1 lote se o preço andar todo o stop.
    perda_por_lote = (sl_distance_price / tick_size) * tick_value
    if perda_por_lote <= 0:
        return 0.0

    lote_bruto = risco_dollar / perda_por_lote

    # Normaliza ao step arredondando para baixo (não estourar o risco).
    passos = math.floor(lote_bruto / lot_step)
    lote = passos * lot_step

    # Clamp em [min_lot, max_lot]. Se nem o min_lot cabe no risco, ainda
    # retornamos min_lot apenas se ele estiver dentro do teto — caso contrário
    # o chamador decide. Mantemos a convenção: clamp simples.
    if lote < min_lot:
        lote = min_lot
    if lote > max_lot:
        lote = max_lot

    # Arredonda para limpar ruído de ponto flutuante do step.
    # Casas decimais derivadas do lot_step (ex.: 0.01 -> 2 casas).
    casas = max(0, -int(math.floor(math.log10(lot_step)))) if lot_step < 1 else 0
    return round(lote, casas)


# ---------------------------------------------------------------------------
# Travas de risco (estado vivo do bot)
# ---------------------------------------------------------------------------
class RiskManager:
    """Mantém o estado de risco e decide se é seguro abrir um novo trade.

    Travas implementadas (todas P0 da mesa redonda):
      - máximo de trades abertos ao mesmo tempo;
      - perda diária máxima (% do saldo) -> pausa no dia;
      - drawdown GLOBAL desde o pico de equity (% ) -> desliga;
      - perdas consecutivas -> pausa no dia.

    O PnL diário e o contador de perdas consecutivas resetam quando vira o dia.
    O pico de equity (referência do drawdown global) NÃO reseta — é global.
    """

    def __init__(
        self,
        max_daily_loss_pct: float,
        max_drawdown_pct: float,
        max_consec_losses: int,
        max_open_trades: int,
    ) -> None:
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_consec_losses = max_consec_losses
        self.max_open_trades = max_open_trades

        # Estado vivo.
        self.equity_peak: float = 0.0        # maior equity já visto (drawdown global)
        self.daily_pnl: float = 0.0          # soma de lucros/perdas do dia
        self.consec_losses: int = 0          # perdas consecutivas (cluster)
        self.current_day: date | None = None  # data do dia corrente (para reset)

    # --- helpers internos ---
    def _roll_day(self, now: datetime | None) -> None:
        """Reseta PnL diário e perdas consecutivas quando o dia muda."""
        hoje = (now or datetime.now()).date()
        if self.current_day is None:
            self.current_day = hoje
        elif hoje != self.current_day:
            self.current_day = hoje
            self.daily_pnl = 0.0
            self.consec_losses = 0

    # --- atualizações de estado ---
    def update_equity(self, equity: float) -> None:
        """Atualiza o pico de equity (referência para o drawdown global)."""
        if equity > self.equity_peak:
            self.equity_peak = equity

    def register_close(self, profit: float) -> None:
        """Registra o fechamento de um trade.

        Soma ao PnL do dia. Se foi perda (profit < 0) incrementa o contador de
        perdas consecutivas; se foi lucro (> 0) zera o contador. Profit == 0
        (scratch) não mexe no contador.
        """
        self.daily_pnl += profit
        if profit < 0:
            self.consec_losses += 1
        elif profit > 0:
            self.consec_losses = 0

    # --- decisão de entrada ---
    def can_open_trade(
        self,
        equity: float,
        balance: float,
        open_positions: int,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """Decide se é seguro abrir um novo trade.

        Retorna (True, "ok") se nenhuma trava disparar, ou (False, motivo) na
        primeira trava violada.
        """
        # Vira o dia se for o caso (reseta PnL diário e perdas seguidas).
        self._roll_day(now)

        # Trava 1 — máximo de posições simultâneas.
        if open_positions >= self.max_open_trades:
            return False, (
                f"Máximo de trades abertos atingido "
                f"({open_positions}/{self.max_open_trades})."
            )

        # Trava 2 — perda diária máxima (% do saldo). daily_pnl é negativo numa perda.
        limite_diario = self.max_daily_loss_pct / 100.0 * balance
        if self.daily_pnl <= -limite_diario:
            return False, (
                f"Perda diária máxima atingida "
                f"(PnL dia {self.daily_pnl:.2f} <= -{limite_diario:.2f})."
            )

        # Trava 3 — drawdown GLOBAL desde o pico de equity. (Buraco crítico da mesa.)
        if self.equity_peak > 0:
            dd_pct = (self.equity_peak - equity) / self.equity_peak * 100.0
            if dd_pct >= self.max_drawdown_pct:
                return False, (
                    f"Drawdown global máximo atingido "
                    f"({dd_pct:.2f}% >= {self.max_drawdown_pct:.2f}%)."
                )

        # Trava 4 — perdas consecutivas (perdas vêm em cluster -> pausa no dia).
        if self.consec_losses >= self.max_consec_losses:
            return False, (
                f"Perdas consecutivas no limite "
                f"({self.consec_losses}/{self.max_consec_losses})."
            )

        return True, "ok"


__all__ = ["calculate_lot", "RiskManager"]
