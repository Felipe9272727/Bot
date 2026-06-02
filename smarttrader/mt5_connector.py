"""Conector com o terminal MetaTrader 5.

Encapsula o pacote oficial ``MetaTrader5`` (que só roda no terminal do usuário,
geralmente Windows). O import é **protegido**: este módulo importa em qualquer
sistema operacional (Linux/macOS inclusive, sem o pacote), mas os métodos que
falam com o terminal só funcionam quando o pacote está instalado E há conexão
ativa. Caso contrário, levantam ``RuntimeError`` com mensagem clara.

Assim, os demais módulos (estratégia, risco, backtest) continuam testáveis em
qualquer máquina sem depender do MT5.

Contrato: ver docs/ARQUITETURA.md.
"""

from __future__ import annotations

import logging

# --- Import protegido do MetaTrader5 -------------------------------------
# Em Linux/macOS o pacote não existe; o módulo PRECISA importar mesmo assim.
try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - depende do ambiente
    mt5 = None

# --- Import protegido do pandas ------------------------------------------
# Idealmente o pandas importa normalmente; protegemos por garantia para que
# `import smarttrader.mt5_connector` nunca quebre num ambiente mínimo.
try:
    import pandas as pd
except ImportError:  # pragma: no cover - depende do ambiente
    pd = None


log = logging.getLogger(__name__)


# Mensagem padrão quando o MT5 não está disponível (rodando fora do Windows
# ou sem o terminal instalado).
_ERRO_SEM_MT5 = "MetaTrader5 não disponível: rode no Windows com o terminal MT5"


def _map_timeframe(timeframe):
    """Mapeia uma string de timeframe ("H1", "D1", "M15"...) para a constante
    ``mt5.TIMEFRAME_*`` correspondente.

    Aceita também já receber um inteiro (constante do mt5), repassando-o direto.
    Faz *fallback* para H1 com aviso caso a string seja desconhecida.
    """
    if mt5 is None:
        raise RuntimeError(_ERRO_SEM_MT5)

    # Se já for um inteiro, assume que é uma constante válida do mt5.
    if isinstance(timeframe, int):
        return timeframe

    tabela = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }
    chave = str(timeframe).upper()
    if chave not in tabela:
        log.warning("Timeframe '%s' desconhecido; usando fallback H1.", timeframe)
        return mt5.TIMEFRAME_H1
    return tabela[chave]


class MT5Connector:
    """Fachada fina sobre o pacote ``MetaTrader5``.

    Uso típico::

        c = MT5Connector()
        c.connect(login=123, password="...", server="MetaQuotes-Demo")
        df = c.get_rates("EURUSD", "H1", 500)
        c.shutdown()
    """

    def __init__(self):
        # True após connect() bem-sucedido.
        self._conectado = False

    # ------------------------------------------------------------------
    # Guardas internas
    # ------------------------------------------------------------------
    def _checar_mt5(self):
        """Garante que o pacote MT5 está disponível neste sistema operacional."""
        if mt5 is None:
            raise RuntimeError(_ERRO_SEM_MT5)

    def _checar_conexao(self):
        """Garante pacote disponível E conexão ativa."""
        self._checar_mt5()
        if not self._conectado:
            raise RuntimeError(
                "MT5 não conectado: chame connect() antes de operar"
            )

    # ------------------------------------------------------------------
    # Conexão
    # ------------------------------------------------------------------
    def connect(self, login, password, server, path=None) -> bool:
        """Inicializa o terminal e faz login na conta.

        Faz ``mt5.initialize`` seguido de ``mt5.login``. Retorna True em caso de
        sucesso; em falha, loga ``mt5.last_error()`` e retorna False.

        Args:
            login:    número da conta (int).
            password: senha da conta.
            server:   nome do servidor/broker (ex.: "MetaQuotes-Demo").
            path:     caminho opcional para o terminal64.exe.
        """
        self._checar_mt5()

        # initialize: se 'path' for dado, aponta para o terminal64.exe.
        if path:
            ok = mt5.initialize(path)
        else:
            ok = mt5.initialize()
        if not ok:
            log.error("mt5.initialize falhou: %s", mt5.last_error())
            self._conectado = False
            return False

        # login na conta (login é inteiro; server é o nome do broker).
        if not mt5.login(int(login), password=password, server=server):
            log.error("mt5.login falhou: %s", mt5.last_error())
            mt5.shutdown()
            self._conectado = False
            return False

        self._conectado = True
        log.info("Conectado ao MT5 (login=%s, server=%s).", login, server)
        return True

    def shutdown(self):
        """Encerra a conexão com o terminal (se houver)."""
        if mt5 is not None and self._conectado:
            mt5.shutdown()
        self._conectado = False

    # ------------------------------------------------------------------
    # Dados de mercado
    # ------------------------------------------------------------------
    def get_rates(self, symbol, timeframe, count):
        """Retorna ``count`` candles de ``symbol`` como ``pandas.DataFrame``.

        Usa ``mt5.copy_rates_from_pos`` (posição 0 = candle mais recente).
        Colunas: open, high, low, close e volume (tick_volume) se houver.
        Índice: datetime UTC, convertido do campo 'time' (epoch em segundos).
        """
        self._checar_conexao()
        if pd is None:
            raise RuntimeError("pandas não instalado (necessário para get_rates).")

        tf = _map_timeframe(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"Sem cotações para {symbol}/{timeframe}: {mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        # 'time' vem como epoch em segundos -> índice datetime em UTC.
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        # Mantém open/high/low/close e o volume (se existir na resposta).
        colunas = ["open", "high", "low", "close", "tick_volume", "real_volume"]
        df = df[[c for c in colunas if c in df.columns]]
        return df

    # ------------------------------------------------------------------
    # Informações de símbolo / conta
    # ------------------------------------------------------------------
    def symbol_info(self, symbol) -> dict:
        """Retorna informações do símbolo necessárias para risco/execução.

        Garante ``symbol_select`` (o símbolo precisa estar visível no Market
        Watch para que info/cotações fiquem disponíveis).
        """
        self._checar_conexao()

        # Garante que o símbolo está selecionado no Market Watch.
        if not mt5.symbol_select(symbol, True):
            log.warning("symbol_select(%s) falhou: %s", symbol, mt5.last_error())

        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(
                f"symbol_info({symbol}) retornou None: {mt5.last_error()}"
            )
        return {
            "tick_value": info.trade_tick_value,
            "tick_size": info.trade_tick_size,
            "point": info.point,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "spread": info.spread,
        }

    def account_info(self) -> dict:
        """Retorna saldo/patrimônio/margem livre/moeda da conta."""
        self._checar_conexao()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"account_info() retornou None: {mt5.last_error()}")
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin_free": info.margin_free,
            "currency": info.currency,
        }

    # ------------------------------------------------------------------
    # Posições
    # ------------------------------------------------------------------
    def positions(self, symbol=None, magic=None) -> list:
        """Lista posições abertas, filtrando por símbolo e/ou magic se dados.

        Usa ``mt5.positions_get``. Cada posição é um dict com:
        ticket, symbol, type (0=buy, 1=sell), volume, price_open, sl, tp,
        profit, magic.
        """
        self._checar_conexao()

        # Se symbol dado, já filtra no terminal; senão, pega todas.
        if symbol is not None:
            posicoes = mt5.positions_get(symbol=symbol)
        else:
            posicoes = mt5.positions_get()
        if posicoes is None:
            posicoes = ()

        resultado = []
        for p in posicoes:
            # Filtro por magic (não há filtro nativo no positions_get).
            if magic is not None and p.magic != magic:
                continue
            resultado.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": p.type,  # 0=buy, 1=sell
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit": p.profit,
                    "magic": p.magic,
                }
            )
        return resultado

    # ------------------------------------------------------------------
    # Execução de ordens
    # ------------------------------------------------------------------
    def _type_filling(self, symbol):
        """Escolhe um type_filling compatível com o símbolo.

        Brokers diferem: alguns aceitam FOK, outros IOC. Inspecionamos o
        ``filling_mode`` do símbolo e escolhemos um modo aceitável, caindo
        para FOK como padrão conservador.
        """
        info = mt5.symbol_info(symbol)
        if info is not None:
            modo = info.filling_mode
            # filling_mode é um bitmask: bit 1 = FOK, bit 2 = IOC.
            if modo & 1:
                return mt5.ORDER_FILLING_FOK
            if modo & 2:
                return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_FOK

    def open_trade(self, symbol, direction, lot, sl, tp, magic,
                   comment="SmartTrader") -> dict:
        """Abre uma ordem a mercado (``TRADE_ACTION_DEAL``).

        direction: 1 = COMPRAR (ORDER_TYPE_BUY @ ask),
                  -1 = VENDER  (ORDER_TYPE_SELL @ bid).

        REGRA DE SEGURANÇA inegociável: SEMPRE exige Stop Loss válido (sl > 0).
        Se ``sl`` <= 0, a ordem NÃO é enviada e retorna erro.

        Retorna dict com: sucesso (bool), retcode, comment e ticket.
        """
        self._checar_conexao()

        # Regra de segurança: nenhuma ordem sem Stop Loss.
        if sl is None or sl <= 0:
            return {
                "sucesso": False,
                "retcode": None,
                "comment": "ordem recusada: Stop Loss obrigatório (sl<=0)",
                "ticket": None,
            }

        if direction not in (1, -1):
            return {
                "sucesso": False,
                "retcode": None,
                "comment": f"direção inválida: {direction} (use 1 ou -1)",
                "ticket": None,
            }

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {
                "sucesso": False,
                "retcode": None,
                "comment": f"sem tick para {symbol}: {mt5.last_error()}",
                "ticket": None,
            }

        if direction == 1:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # MqlTradeRequest (montado como dict, conforme a API Python do MT5).
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp) if tp and tp > 0 else 0.0,
            "deviation": 20,  # desvio máximo de preço aceitável (pontos)
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._type_filling(symbol),
        }

        resultado = mt5.order_send(request)
        if resultado is None:
            return {
                "sucesso": False,
                "retcode": None,
                "comment": f"order_send retornou None: {mt5.last_error()}",
                "ticket": None,
            }
        sucesso = resultado.retcode == mt5.TRADE_RETCODE_DONE
        if not sucesso:
            log.error("open_trade falhou: retcode=%s %s",
                      resultado.retcode, resultado.comment)
        return {
            "sucesso": sucesso,
            "retcode": resultado.retcode,
            "comment": resultado.comment,
            "ticket": getattr(resultado, "order", None),
        }

    def modify_sl(self, ticket, sl, tp=None) -> bool:
        """Modifica SL (e opcionalmente TP) de uma posição existente.

        Usa ``TRADE_ACTION_SLTP``. Se ``tp`` não for dado, preserva o TP atual.
        """
        self._checar_conexao()

        # Recupera a posição para descobrir o símbolo e o TP atual.
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            log.error("modify_sl: posição %s não encontrada.", ticket)
            return False
        p = pos[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": p.symbol,
            "position": int(ticket),
            "sl": float(sl),
            "tp": float(tp) if tp is not None else p.tp,
        }
        resultado = mt5.order_send(request)
        if resultado is None:
            log.error("modify_sl: order_send None: %s", mt5.last_error())
            return False
        ok = resultado.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            log.error("modify_sl falhou: retcode=%s %s",
                      resultado.retcode, resultado.comment)
        return ok

    def close_partial(self, ticket, volume) -> bool:
        """Fecha ``volume`` lotes da posição ``ticket`` (fechamento parcial).

        Envia uma ordem a mercado no sentido OPOSTO ao da posição
        (``TRADE_ACTION_DEAL``), amarrada via ``position=ticket``.
        """
        self._checar_conexao()

        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            log.error("close_partial: posição %s não encontrada.", ticket)
            return False
        p = pos[0]

        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            log.error("close_partial: sem tick para %s.", p.symbol)
            return False

        # Ordem oposta ao tipo da posição.
        if p.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": float(volume),
            "type": order_type,
            "position": int(ticket),
            "price": price,
            "deviation": 20,
            "magic": p.magic,
            "comment": "SmartTrader close_partial",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._type_filling(p.symbol),
        }
        resultado = mt5.order_send(request)
        if resultado is None:
            log.error("close_partial: order_send None: %s", mt5.last_error())
            return False
        ok = resultado.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            log.error("close_partial falhou: retcode=%s %s",
                      resultado.retcode, resultado.comment)
        return ok
