"""Motor de viés por notícias (sinal de direção).

Lê (no futuro) notícias macro em tempo real, interpreta o impacto e devolve um
**viés de direção** (comprar / vender / neutro) + confiança para um ativo.

Contrato: ver docs/ARQUITETURA.md e docs/IA_NOTICIAS.md.

------------------------------------------------------------------------------
HONESTIDADE OBRIGATÓRIA (não é bola de cristal):
    Notícia "óbvia" já entra no preço em segundos, precificada por algoritmos
    institucionais. A borda de varejo NÃO está em reagir à manchete, e sim em
    capturar *mudança de narrativa macro* que dura horas/dias (swing). O alfa de
    IA-de-notícias vem caindo conforme mais gente usa (Sharpe de estratégias
    GPT-4 caiu de ~6,5 em 2021 para ~1,2 em 2024). Por isso tratamos a IA como
    **veto / viés de qualidade**, não como gerador mágico de entradas.

    Princípio de design: o modelo DEVE poder dizer "não sei" (NEUTRO) em vez de
    inventar convicção. Em dúvida, falha ou ambiguidade, o comportamento é
    *fail-safe*: bias=0, confidence=0 (e stale=True quando algo deu errado).
------------------------------------------------------------------------------

ESTADO ATUAL: este módulo é um STUB plugável e honesto. ``get_bias`` retorna
sempre NEUTRO. Os pontos de extensão (FinBERT / LLM / feeds GDELT-RSS-Finnhub)
estão marcados com TODO e docstrings claros indicando ONDE plugar cada peça.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Bias:
    """Viés de direção para um símbolo.

    Campos:
        symbol:     ativo (ex.: "USDCAD").
        bias:       1 = comprar, -1 = vender, 0 = neutro/não operar.
        confidence: 0..1 (quão forte é o viés).
        blocked:    True em janela de evento de alto impacto (não operar o spike).
        stale:      True quando o viés é velho (TTL expirado) OU houve falha
                    interna (fail-safe). A técnica não deve seguir um viés stale.
        rationale:  explicação curta em texto (cadeia causal do LLM).
    """

    symbol: str
    bias: int  # 1 / -1 / 0
    confidence: float  # 0..1
    blocked: bool = False
    stale: bool = False
    rationale: str = ""


def _bias_neutro(symbol: str, rationale: str, stale: bool = False,
                 blocked: bool = False) -> Bias:
    """Cria um viés NEUTRO (fail-safe). Reutilizado em todo caminho de dúvida."""
    return Bias(
        symbol=symbol,
        bias=0,
        confidence=0.0,
        blocked=blocked,
        stale=stale,
        rationale=rationale,
    )


# Termos de busca/relevância por símbolo: usados para filtrar as notícias ao
# vivo (RSS/GDELT) que importam para cada ativo. Ajustável conforme necessário.
SYMBOL_QUERY: dict[str, list[str]] = {
    "USDCAD": ["oil", "crude", "opec", "canada", "canadian dollar", "fed", "boc"],
    "USOIL":  ["oil", "crude", "opec", "brent", "wti", "energy"],
    "XAUUSD": ["gold", "inflation", "fed", "war", "safe haven", "rates"],
    "EURUSD": ["euro", "ecb", "fed", "eurozone", "inflation"],
    "GBPUSD": ["pound", "boe", "uk", "britain", "inflation"],
    "USDJPY": ["yen", "boj", "japan", "fed", "rates"],
    "SPX":    ["stocks", "s&p", "wall street", "recession", "earnings", "fed"],
    "BTCUSD": ["bitcoin", "crypto", "etf", "sec"],
}


class NewsBiasEngine:
    """Motor de viés por notícias.

    Hoje é um stub que sempre devolve NEUTRO. A estrutura abaixo deixa claros os
    pontos de plugue para a implementação real (ingestão -> pré-filtro FinBERT
    -> interpretação LLM -> cache com TTL -> modo defensivo de calendário).
    """

    def __init__(self, news_api_key=None, llm_api_key=None,
                 high_impact_calendar=None, override_bias=None):
        """Configura chaves de API e dependências injetáveis.

        Args:
            news_api_key: chave da fonte de notícias (Finnhub/GDELT/Alpha Vantage).
            llm_api_key:  chave do provedor de LLM usado na interpretação macro.
            high_impact_calendar: fonte do calendário econômico de alto impacto.
                Pode ser, p.ex., um callable ``fn(now) -> bool`` que diz se
                estamos na janela de ±15 min de NFP/FOMC/CPI. Usado por
                ``_in_high_impact_window``. Quando None, assume-se "sem evento".
            override_bias: MODO DE TESTE. Quando dado, ``get_bias`` o usa em vez
                do fluxo normal — permite testes determinísticos. Pode ser:
                  * um ``Bias`` já pronto (retornado como veio, com symbol ajustado
                    se vier vazio); ou
                  * um callable ``fn(symbol) -> Bias`` (chamado a cada get_bias).
                Se o callable lançar exceção, o fail-safe captura e devolve NEUTRO
                com stale=True (a IA NUNCA derruba o trader).
        """
        self.news_api_key = news_api_key
        self.llm_api_key = llm_api_key
        # Calendário de eventos de alto impacto (injetável p/ testes/implementação).
        self.high_impact_calendar = high_impact_calendar
        # Gancho de override para testes determinísticos.
        self.override_bias = override_bias

        # (4) Cache de viés por símbolo: { symbol: (Bias, epoch_de_criacao) }.
        # Preenchido pela implementação real; usado para respeitar o TTL e evitar
        # chamar o LLM a cada consulta do trader.
        self._cache: dict[str, tuple[Bias, float]] = {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def get_bias(self, symbol: str) -> Bias:
        """Retorna o viés de direção para ``symbol``.

        Garantias de contrato (sempre válidas, inclusive no stub):
            * bias ∈ {-1, 0, 1};
            * confidence ∈ [0, 1];
            * QUALQUER exceção interna -> NEUTRO com stale=True (fail-safe);
              a IA nunca derruba o trader.

        STUB ATUAL: sempre NEUTRO. Quando plugado, o fluxo será:
            1. Se há viés em cache dentro do TTL -> retorná-lo (confiança decaída).
            2. Se estamos em janela de alto impacto -> blocked=True.
            3. Buscar notícias novas relevantes      (_fetch_news).
            4. Pré-filtrar sentimento barato/FinBERT  (_score_sentiment).
            5. Interpretar macro -> bias+confidence    (_interpret_macro / LLM).
            6. Atualizar cache e retornar.
            7. Qualquer falha -> NEUTRO (fail-safe).
        """
        # --- Fail-safe global: nada aqui pode derrubar o trader. ----------
        try:
            # MODO DE TESTE: override determinístico tem prioridade.
            if self.override_bias is not None:
                return self._aplicar_override(symbol)

            # (5) Modo defensivo: nunca tentar adivinhar o spike de evento.
            if self._in_high_impact_window(datetime.now(timezone.utc)):
                return _bias_neutro(
                    symbol,
                    rationale="janela de evento de alto impacto: operacao bloqueada",
                    blocked=True,
                )

            # --- Comportamento atual: stub honesto e neutro ---------------
            # ONDE PLUGAR O FLUXO REAL (ver docs/IA_NOTICIAS.md):
            #   noticias = self._fetch_news(symbol)            # feeds GDELT/RSS/Finnhub
            #   if not noticias:
            #       return _bias_neutro(symbol, "sem noticia nova relevante")
            #   scores = self._score_sentiment(...)            # FinBERT (pré-filtro)
            #   vies = self._interpret_macro(symbol, noticias) # LLM (macro->ativo)
            #   self._cache[symbol] = (vies, time.time())
            #   return vies
            return _bias_neutro(
                symbol,
                rationale="stub: IA de noticias ainda nao plugada",
            )
        except Exception as exc:  # noqa: BLE001 — fail-safe é proposital e amplo.
            # Qualquer falha (API, LLM, calendário, bug) vira NEUTRO + stale.
            return _bias_neutro(
                symbol,
                rationale=f"fail-safe: erro interno ({exc!r})",
                stale=True,
            )

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------
    def _aplicar_override(self, symbol: str) -> Bias:
        """Resolve o ``override_bias`` (Bias pronto ou callable) para testes.

        Levanta exceção naturalmente se o callable falhar; o fail-safe de
        ``get_bias`` cuida disso (vira NEUTRO + stale=True).
        """
        ov = self.override_bias
        vies = ov(symbol) if callable(ov) else ov
        # Se vier um Bias com symbol vazio, preenche com o solicitado.
        if isinstance(vies, Bias) and not vies.symbol:
            vies.symbol = symbol
        return vies

    def _in_high_impact_window(self, now) -> bool:
        """(5) Indica se ``now`` cai numa janela de evento de alto impacto
        (±15 min de NFP / FOMC / CPI etc.) -> deve gerar ``blocked=True``.

        Delega ao ``high_impact_calendar`` injetado, se houver:
            * callable -> ``high_impact_calendar(now)`` (bool);
            * objeto com método ``in_window(now)`` -> usa-o.
        Sem calendário configurado, retorna False (assume "sem evento").

        TODO (implementação real): consultar calendário econômico (Finnhub) ~1x/h,
        cachear os horários dos eventos de alto impacto e devolver True nos
        ±15 min ao redor de cada um.
        """
        cal = self.high_impact_calendar
        if cal is None:
            return False
        if callable(cal):
            return bool(cal(now))
        em_janela = getattr(cal, "in_window", None)
        if callable(em_janela):
            return bool(em_janela(now))
        return False

    # ------------------------------------------------------------------
    # Pontos de extensão (TODO) — privados, ainda não implementados
    # ------------------------------------------------------------------
    def _fetch_news(self, symbol: str) -> list:
        """(1) Ingestão de notícias relevantes para ``symbol``.

        ONDE PLUGAR OS FEEDS (docs/IA_NOTICIAS.md):
            * RSS Reuters/Investing/FXStreet a cada ~30-60s (baixa latência);
            * GDELT 2.0 DOC API a cada ~15 min (cobertura global, tom/temas);
            * calendário econômico Finnhub ~1x/h (eventos de alto impacto);
            * Alpha Vantage News (sentimento já pontuado por ticker).
        Deduplicar por hash de título/URL e filtrar relevância por símbolo.

        Deve retornar uma lista de itens (dicts com título, texto, fonte, ts).
        """
        raise NotImplementedError("_fetch_news ainda nao plugado")

    def _score_sentiment(self, texts: list) -> list:
        """(2) Pré-filtro barato de sentimento.

        ONDE PLUGAR O FinBERT: rodar FinBERT (treinado em finanças, ~0.88 acc)
        LOCALMENTE para descartar notícia neutra/ruído ANTES de gastar uma chamada
        de LLM (economia de custo). Léxicos (VADER, Loughran-McDonald) só como
        baseline — VADER vai mal em finanças.

        Deve retornar scores de sentimento por texto.
        """
        raise NotImplementedError("_score_sentiment ainda nao plugado")

    def _interpret_macro(self, symbol: str, news: list) -> Bias:
        """(3) Interpretação macro -> bias + confidence (via LLM).

        ONDE PLUGAR O LLM: só roda quando há notícia nova relevante (controla
        custo). O prompt deve pedir a cadeia causal e as FORÇAS CONFLITANTES, com
        instrução explícita de devolver NEUTRO em ambiguidade — o modelo precisa
        poder dizer "não sei" (ver exemplo "crise no petróleo" em IA_NOTICIAS.md).

        Deve retornar um ``Bias``.
        """
        raise NotImplementedError("_interpret_macro ainda nao plugado")

    # ------------------------------------------------------------------
    # Caminho USÁVEL hoje: viés a partir de manchetes (news_mapper + FinBERT)
    # ------------------------------------------------------------------
    def bias_from_headlines(self, symbol, headlines, scorer=None) -> Bias:
        """Gera um ``Bias`` a partir de manchetes, SEM precisar de LLM.

        - Direção: ``news_mapper`` (regras macro->direção; trata forças
          conflitantes, ex.: petróleo↑ x safe-haven).
        - Confiança: a do ``news_mapper``, opcionalmente REFORÇADA por um
          ``FinBertSentiment`` (parâmetro ``scorer``): sentimento forte e
          consistente eleva a confiança; fraco, atenua.

        É o ponto onde o seu modelo treinado no Colab se conecta::

            from smarttrader.sentiment import FinBertSentiment
            fb = FinBertSentiment("finbert_ft")          # modelo do Colab
            vies = engine.bias_from_headlines("USDCAD", manchetes, scorer=fb)

        Fail-safe: qualquer erro -> Bias neutro com ``stale=True``.
        """
        try:
            from .news_mapper import bias_for_symbol, detect_themes
            temas = detect_themes(headlines)
            b, conf, rationale = bias_for_symbol(symbol, temas)
            if scorer is not None and headlines:
                # reforço leve pela confiança média de sentimento (0..1)
                sent = scorer.avg_confidence(headlines)
                conf = max(0.0, min(1.0, conf * (0.5 + 0.5 * sent)))
            return Bias(symbol=symbol, bias=int(b), confidence=float(conf),
                        rationale=rationale)
        except Exception as exc:  # noqa: BLE001 - fail-safe: nunca derruba o trader
            return _bias_neutro(
                symbol, f"fail-safe bias_from_headlines: {exc!r}", stale=True)

    def bias_from_live_news(self, symbol, scorer=None, max_items: int = 40) -> Bias:
        """Busca notícias AO VIVO (RSS + GDELT), filtra por relevância do símbolo
        e gera um ``Bias`` automaticamente — sem manchetes manuais.

        Pipeline:
          1. RSS (``DEFAULT_RSS_FEEDS``) + GDELT (busca pelos termos do símbolo);
          2. dedup + filtro de relevância (``SYMBOL_QUERY``);
          3. ``bias_from_headlines`` (news_mapper -> direção; FinBERT opcional).

        Fail-safe: sem notícia relevante ou qualquer erro -> Bias neutro
        (``stale=True`` em caso de erro). A IA nunca derruba o trader.
        """
        try:
            from . import news_sources as ns

            kws = SYMBOL_QUERY.get(symbol.upper(), [])
            itens = list(ns.fetch_rss(ns.DEFAULT_RSS_FEEDS))
            if kws:
                itens += list(ns.fetch_gdelt(" OR ".join(kws[:4])))
            itens = ns.dedup(itens)
            if kws:
                itens = ns.filter_relevant(itens, kws)
            itens = itens[:max_items]

            manchetes = [f"{it.title} {it.summary}".strip() for it in itens]
            if not manchetes:
                return _bias_neutro(symbol, "sem noticia relevante ao vivo")
            return self.bias_from_headlines(symbol, manchetes, scorer=scorer)
        except Exception as exc:  # noqa: BLE001 - fail-safe
            return _bias_neutro(symbol, f"fail-safe live: {exc!r}", stale=True)


# ----------------------------------------------------------------------------
# EXEMPLO COMENTADO — como um viés REAL seria montado
# ----------------------------------------------------------------------------
# Cenário: "crise no petróleo" (alta forte e súbita do barril).
#
#   Forças conflitantes sobre USDCAD:
#     - Petróleo sobe  -> CAD (exportador) tende a fortalecer -> USDCAD CAI.
#     - Crise geopolítica liga safe-haven no USD -> empurra USDCAD pra CIMA
#       (e o ouro pra cima também).
#
#   O LLM pondera qual força domina:
#     - Se a alta do petróleo domina e o risk-off é moderado:
#           Bias(symbol="USDCAD", bias=-1, confidence=0.62,
#                rationale="Alta do petroleo favorece CAD; safe-haven USD "
#                          "compensa em parte")
#     - Se as forças se cancelam (ambiguidade):
#           Bias(symbol="USDCAD", bias=0, confidence=0.10,
#                rationale="Petroleo (CAD+) x safe-haven (USD+) se anulam")
#
#   Lembrete honesto: se a notícia já é pública e óbvia, provavelmente já está
#   precificada — o valor está na MUDANÇA DE NARRATIVA macro de horas/dias, e a
#   IA atua como veto/viés de qualidade, não como gatilho de entrada.
