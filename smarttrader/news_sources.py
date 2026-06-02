"""Ingestão de notícias (fontes de dados) que alimenta o motor de viés.

Este módulo é a camada de **INGEST** do diagrama em docs/IA_NOTICIAS.md:

    [RSS / GDELT / Finnhub calendário]   <-- ESTE MÓDULO
            │  ingest
            ▼
    [Dedup + filtro de relevância por símbolo]   <-- dedup() / filter_relevant()
            │
            ▼
    [FinBERT -> LLM -> cache -> HTTP]   (camadas seguintes, em news_ai.py)

Quem consome: ``smarttrader/news_ai.py`` (NewsBiasEngine._fetch_news) plugará
estas funções para coletar notícias antes do pré-filtro FinBERT e do LLM.

------------------------------------------------------------------------------
PRINCÍPIOS DE ROBUSTEZ (rede é OPCIONAL):
    * As libs de rede (``feedparser`` e ``requests``) têm import PROTEGIDO. O
      módulo importa e roda mesmo sem elas instaladas — isso mantém todo o
      código TESTÁVEL OFFLINE (sem rede, via monkeypatch/fakes nos testes).
    * Nenhuma fonte derruba o serviço: erro de rede, parse ou lib ausente vira
      LISTA VAZIA + log claro. A IA nunca pode quebrar o trader (fail-safe).
------------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Imports de rede PROTEGIDOS — o módulo precisa importar mesmo sem as libs.
# Os testes rodam OFFLINE; em produção o usuário instala feedparser/requests.
# ---------------------------------------------------------------------------
try:  # parser de RSS/Atom
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover - depende do ambiente
    feedparser = None  # type: ignore

try:  # cliente HTTP (GDELT / Finnhub)
    import requests  # type: ignore
except ImportError:  # pragma: no cover - depende do ambiente
    requests = None  # type: ignore


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelo de dado normalizado
# ---------------------------------------------------------------------------
@dataclass
class NewsItem:
    """Item de notícia normalizado, comum a todas as fontes.

    Campos:
        title:     manchete.
        summary:   resumo/descrição curta (pode ser vazio).
        url:       link original (usado, junto do título, para dedup).
        source:    rótulo da fonte (ex.: "rss", "gdelt", domínio do feed).
        published: data/hora de publicação em UTC, ou ``None`` se desconhecida.
    """

    title: str
    summary: str
    url: str
    source: str
    published: datetime | None = None


# ---------------------------------------------------------------------------
# Feeds RSS padrão (públicos). O usuário pode AJUSTAR/expandir esta lista.
# Reuters/Investing/FXStreet costumam mudar suas URLs de RSS; valide em produção.
# Servem como baixa latência e custo zero (ver tabela em IA_NOTICIAS.md).
# ---------------------------------------------------------------------------
DEFAULT_RSS_FEEDS: list[str] = [
    # Reuters — mercados / negócios (URL plausível; ajuste se mudar).
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/news/wealth",
    # Investing.com — notícias econômicas/forex.
    "https://www.investing.com/rss/news_285.rss",
    # FXStreet — análise e notícias de forex.
    "https://www.fxstreet.com/rss/news",
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _struct_time_to_datetime(parsed) -> datetime | None:
    """Converte um ``time.struct_time`` (feedparser) para ``datetime`` UTC.

    Retorna ``None`` se o valor for ausente/inválido — nunca levanta.
    """
    if not parsed:
        return None
    try:
        # feedparser entrega struct_time em UTC nos campos *_parsed.
        import calendar

        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_iso_datetime(value) -> datetime | None:
    """Tenta interpretar uma string de data ISO/variantes -> ``datetime`` UTC.

    Aceita formatos comuns da GDELT (ex.: ``YYYYMMDDTHHMMSSZ``) e ISO-8601.
    Retorna ``None`` em qualquer falha (nunca levanta).
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    # Formato compacto da GDELT: 20260602T134000Z
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Último recurso: ISO-8601 nativo.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Fonte 1 — RSS (Reuters/Investing/FXStreet): baixa latência, custo zero.
# ---------------------------------------------------------------------------
def fetch_rss(feed_urls: list[str], timeout: int = 10) -> list[NewsItem]:
    """Coleta e normaliza notícias de uma lista de feeds RSS/Atom.

    Usa ``feedparser``. Cada feed é independente: se um falha (rede/parse),
    apenas registra log e segue para o próximo — NÃO derruba a coleta.

    Args:
        feed_urls: URLs dos feeds (use ``DEFAULT_RSS_FEEDS`` como ponto de partida).
        timeout:   timeout (s) por requisição quando suportado pelo ambiente.

    Returns:
        Lista de ``NewsItem`` (vazia se ``feedparser`` faltar ou tudo falhar).
    """
    if feedparser is None:
        logger.warning(
            "feedparser ausente: fetch_rss retornando vazio. "
            "Instale 'feedparser' para habilitar a coleta por RSS."
        )
        return []

    items: list[NewsItem] = []
    for url in feed_urls or []:
        try:
            # 'timeout' não é parâmetro universal do feedparser; passamos via
            # request_headers/handlers só quando útil. Aqui mantemos simples e
            # tolerante: feedparser não levanta — ele sinaliza erro em .bozo.
            parsed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001 - nenhuma fonte derruba a coleta
            logger.warning("Falha ao buscar feed RSS %s: %r", url, exc)
            continue

        if getattr(parsed, "bozo", 0) and getattr(parsed, "entries", None) in (None, []):
            # bozo=1 com zero entradas costuma indicar feed inacessível/inválido.
            logger.warning("Feed RSS %s inacessivel ou invalido (bozo).", url)
            continue

        feed_meta = getattr(parsed, "feed", {}) or {}
        source = feed_meta.get("title") or url
        for entry in getattr(parsed, "entries", []) or []:
            title = (entry.get("title") or "").strip()
            summary = (entry.get("summary") or entry.get("description") or "").strip()
            link = (entry.get("link") or "").strip()
            published = _struct_time_to_datetime(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            if not title and not link:
                # Entrada sem identificação útil: descarta.
                continue
            items.append(
                NewsItem(
                    title=title,
                    summary=summary,
                    url=link,
                    source=str(source),
                    published=published,
                )
            )

    logger.debug("fetch_rss coletou %d itens de %d feeds.", len(items), len(feed_urls or []))
    return items


# ---------------------------------------------------------------------------
# Fonte 2 — GDELT 2.0 DOC API: cobertura global, tom/temas, risco geopolítico.
# ---------------------------------------------------------------------------
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_gdelt(
    query: str,
    timemins: int = 60,
    max_records: int = 50,
    timeout: int = 10,
) -> list[NewsItem]:
    """Consulta a GDELT 2.0 DOC API (modo ArtList, JSON) e normaliza artigos.

    GDELT dá cobertura global e é útil para risco geopolítico / mudança de
    narrativa macro (ver IA_NOTICIAS.md). É 100% gratuita e sem chave.

    Args:
        query:       termo de busca (ex.: "oil OR USDCAD OR Federal Reserve").
        timemins:    janela retroativa em minutos (ex.: 60 = última hora).
        max_records: limite de artigos retornados.
        timeout:     timeout HTTP (s).

    Returns:
        Lista de ``NewsItem`` (vazia em qualquer erro de rede/parse ou se
        ``requests`` faltar).
    """
    if requests is None:
        logger.warning(
            "requests ausente: fetch_gdelt retornando vazio. "
            "Instale 'requests' para habilitar a GDELT DOC API."
        )
        return []

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_records,
        "timespan": f"{timemins}min",
        "sort": "DateDesc",
    }
    try:
        resp = requests.get(GDELT_DOC_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - rede/parse não derruba o serviço
        logger.warning("Falha na GDELT DOC API (query=%r): %r", query, exc)
        return []

    articles = (data or {}).get("articles", []) or []
    items: list[NewsItem] = []
    for art in articles:
        title = (art.get("title") or "").strip()
        url = (art.get("url") or "").strip()
        domain = (art.get("domain") or "gdelt").strip()
        published = _parse_iso_datetime(art.get("seendate"))
        if not title and not url:
            continue
        items.append(
            NewsItem(
                title=title,
                summary="",  # a DOC API não traz resumo no ArtList.
                url=url,
                source=f"gdelt:{domain}" if domain else "gdelt",
                published=published,
            )
        )

    logger.debug("fetch_gdelt coletou %d artigos para query=%r.", len(items), query)
    return items


# ---------------------------------------------------------------------------
# Fonte 3 — Finnhub: calendário econômico (eventos de alto impacto).
# Alimenta o "modo defensivo" do news_ai.py (janelas de NFP/FOMC/CPI).
# ---------------------------------------------------------------------------
FINNHUB_ECON_CALENDAR = "https://finnhub.io/api/v1/calendar/economic"


def fetch_finnhub_calendar(api_key: str, timeout: int = 10) -> list[dict]:
    """Busca o calendário econômico do Finnhub (eventos macro agendados).

    Diferente das outras fontes, devolve a lista de **eventos** crus (dicts),
    pois o consumidor (modo defensivo em news_ai.py) precisa de campos como
    horário/impacto para decidir as janelas de ±15 min de alto impacto.

    Args:
        api_key: chave do Finnhub (tier grátis: 60 req/min). Se vazia -> [].
        timeout: timeout HTTP (s).

    Returns:
        Lista de dicts de eventos econômicos (vazia se sem chave, sem
        ``requests``, ou em qualquer erro de rede/parse).
    """
    if not api_key:
        logger.warning(
            "fetch_finnhub_calendar sem api_key: retornando []. "
            "Configure a chave do Finnhub para habilitar o calendario."
        )
        return []
    if requests is None:
        logger.warning(
            "requests ausente: fetch_finnhub_calendar retornando vazio. "
            "Instale 'requests' para habilitar o calendario do Finnhub."
        )
        return []

    try:
        resp = requests.get(
            FINNHUB_ECON_CALENDAR, params={"token": api_key}, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - rede/parse não derruba o serviço
        logger.warning("Falha no calendario economico do Finnhub: %r", exc)
        return []

    # A API retorna {"economicCalendar": [ {...}, ... ]}.
    eventos = (data or {}).get("economicCalendar", []) or []
    if not isinstance(eventos, list):
        logger.warning("Resposta inesperada do Finnhub (economicCalendar nao e lista).")
        return []
    logger.debug("fetch_finnhub_calendar coletou %d eventos.", len(eventos))
    return eventos


# ---------------------------------------------------------------------------
# Pós-processamento: dedup + filtro de relevância (próximo passo do diagrama).
# ---------------------------------------------------------------------------
def _item_hash(item: NewsItem) -> str:
    """Hash estável de (título + url) para detectar duplicados entre fontes."""
    base = f"{item.title.strip().lower()}|{item.url.strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def dedup(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicados por hash de (título + url), preservando a ordem.

    A mesma manchete costuma aparecer em várias fontes/feeds; deduplicar evita
    contar a mesma notícia mais de uma vez (e gastar LLM à toa).
    """
    visto: set[str] = set()
    unicos: list[NewsItem] = []
    for item in items or []:
        h = _item_hash(item)
        if h in visto:
            continue
        visto.add(h)
        unicos.append(item)
    logger.debug("dedup: %d -> %d itens.", len(items or []), len(unicos))
    return unicos


def filter_relevant(items: list[NewsItem], keywords: list[str]) -> list[NewsItem]:
    """Filtra itens cujo título OU summary contenha alguma keyword.

    Comparação *case-insensitive* (substring). Sem keywords -> devolve tudo
    (nada a filtrar). É o filtro barato de relevância por símbolo/tema antes do
    FinBERT/LLM.

    Args:
        items:    notícias normalizadas.
        keywords: termos de interesse (ex.: ["oil", "fed", "USDCAD"]).
    """
    if not keywords:
        return list(items or [])

    kws = [k.lower() for k in keywords if k]
    relevantes: list[NewsItem] = []
    for item in items or []:
        texto = f"{item.title} {item.summary}".lower()
        if any(kw in texto for kw in kws):
            relevantes.append(item)
    logger.debug(
        "filter_relevant: %d -> %d itens (keywords=%r).",
        len(items or []),
        len(relevantes),
        keywords,
    )
    return relevantes
