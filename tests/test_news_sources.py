"""Testes da camada de ingestão de notícias (smarttrader/news_sources.py).

Tudo roda OFFLINE — NENHUMA chamada de rede real. As funções de rede
(fetch_rss / fetch_gdelt / fetch_finnhub_calendar) são exercidas via
monkeypatch sobre ``feedparser.parse`` / ``requests.get`` com fakes, validando
a normalização/parsing e os caminhos de falha (lib ausente, sem chave, erro).

Rodar: pytest tests/test_news_sources.py
"""

from datetime import datetime, timezone

import pytest

from smarttrader import news_sources as ns
from smarttrader.news_sources import (
    NewsItem,
    dedup,
    fetch_finnhub_calendar,
    fetch_gdelt,
    fetch_rss,
    filter_relevant,
)


# ---------------------------------------------------------------------------
# Fakes auxiliares (sem rede)
# ---------------------------------------------------------------------------
class _FakeFeed:
    """Imita o objeto retornado por feedparser.parse."""

    def __init__(self, entries, feed=None, bozo=0):
        self.entries = entries
        self.feed = feed or {"title": "Fake Feed"}
        self.bozo = bozo


class _FakeResponse:
    """Imita um requests.Response com .json() e raise_for_status()."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# NewsItem — campos
# ---------------------------------------------------------------------------
def test_newsitem_campos():
    agora = datetime(2026, 6, 2, 13, 40, tzinfo=timezone.utc)
    item = NewsItem(
        title="Oil spikes",
        summary="Brent jumps on supply fears",
        url="http://ex.com/a",
        source="rss",
        published=agora,
    )
    assert item.title == "Oil spikes"
    assert item.summary == "Brent jumps on supply fears"
    assert item.url == "http://ex.com/a"
    assert item.source == "rss"
    assert item.published == agora


def test_newsitem_published_opcional():
    """published tem default None (data desconhecida)."""
    item = NewsItem(title="t", summary="s", url="u", source="src")
    assert item.published is None


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------
def test_dedup_remove_repetidos_mantem_unicos():
    a = NewsItem("Fed hikes", "", "http://x/1", "rss")
    a_dup = NewsItem("Fed hikes", "", "http://x/1", "gdelt")  # mesmo title+url
    b = NewsItem("ECB cuts", "", "http://x/2", "rss")
    resultado = dedup([a, a_dup, b])
    assert len(resultado) == 2
    assert resultado[0] is a  # preserva ordem e primeira ocorrência
    assert resultado[1] is b


def test_dedup_case_insensitive():
    """Título com caixa diferente + mesma URL conta como duplicado."""
    a = NewsItem("Fed Hikes", "", "http://x/1", "rss")
    b = NewsItem("fed hikes", "", "HTTP://X/1", "gdelt")
    assert len(dedup([a, b])) == 1


def test_dedup_lista_vazia():
    assert dedup([]) == []


# ---------------------------------------------------------------------------
# filter_relevant
# ---------------------------------------------------------------------------
def test_filter_relevant_por_keyword_no_titulo():
    a = NewsItem("Oil prices surge", "market update", "u1", "rss")
    b = NewsItem("Stocks rally", "equities up", "u2", "rss")
    res = filter_relevant([a, b], ["oil"])
    assert res == [a]


def test_filter_relevant_no_summary():
    """Keyword presente só no summary também faz casar."""
    a = NewsItem("Daily wrap", "Federal Reserve signals pause", "u1", "rss")
    res = filter_relevant([a], ["federal reserve"])
    assert res == [a]


def test_filter_relevant_case_insensitive():
    a = NewsItem("USDCAD outlook", "", "u1", "rss")
    res = filter_relevant([a], ["usdcad"])
    assert res == [a]
    res2 = filter_relevant([a], ["USDCAD"])
    assert res2 == [a]


def test_filter_relevant_sem_keywords_devolve_tudo():
    a = NewsItem("x", "", "u1", "rss")
    b = NewsItem("y", "", "u2", "rss")
    assert filter_relevant([a, b], []) == [a, b]


def test_filter_relevant_nenhuma_casa():
    a = NewsItem("x", "y", "u1", "rss")
    assert filter_relevant([a], ["zzz"]) == []


# ---------------------------------------------------------------------------
# fetch_rss — via monkeypatch em feedparser.parse (sem rede)
# ---------------------------------------------------------------------------
def test_fetch_rss_normaliza(monkeypatch):
    import time

    # struct_time UTC equivalente a 2026-06-02 13:40:00.
    st = time.gmtime(datetime(2026, 6, 2, 13, 40, tzinfo=timezone.utc).timestamp())
    entries = [
        {
            "title": "Oil spikes",
            "summary": "Brent jumps",
            "link": "http://news/1",
            "published_parsed": st,
        },
        {
            "title": "ECB decision",
            "description": "rate hold",  # usa 'description' quando falta summary
            "link": "http://news/2",
        },
    ]
    fake = _FakeFeed(entries, feed={"title": "Reuters"})

    # Garante que o módulo "tem" feedparser e intercepta parse.
    monkeypatch.setattr(ns, "feedparser", type("FP", (), {"parse": staticmethod(lambda url: fake)}))

    out = fetch_rss(["http://feed"])
    assert len(out) == 2
    assert out[0].title == "Oil spikes"
    assert out[0].summary == "Brent jumps"
    assert out[0].url == "http://news/1"
    assert out[0].source == "Reuters"
    assert out[0].published == datetime(2026, 6, 2, 13, 40, tzinfo=timezone.utc)
    # Segundo item usa 'description' e fica sem data.
    assert out[1].summary == "rate hold"
    assert out[1].published is None


def test_fetch_rss_feed_que_falha_nao_derruba(monkeypatch):
    """Um feed que levanta exceção é ignorado; os demais seguem."""
    ok = _FakeFeed([{"title": "ok", "summary": "", "link": "http://ok"}])

    def parse(url):
        if url == "http://bad":
            raise RuntimeError("rede caiu")
        return ok

    monkeypatch.setattr(ns, "feedparser", type("FP", (), {"parse": staticmethod(parse)}))
    out = fetch_rss(["http://bad", "http://good"])
    assert len(out) == 1
    assert out[0].title == "ok"


def test_fetch_rss_bozo_sem_entradas_descartado(monkeypatch):
    fake = _FakeFeed([], bozo=1)
    monkeypatch.setattr(ns, "feedparser", type("FP", (), {"parse": staticmethod(lambda url: fake)}))
    assert fetch_rss(["http://feed"]) == []


def test_fetch_rss_sem_feedparser(monkeypatch):
    """Caminho 'lib ausente': feedparser=None -> [] sem explodir."""
    monkeypatch.setattr(ns, "feedparser", None)
    assert fetch_rss(["http://feed"]) == []


# ---------------------------------------------------------------------------
# fetch_gdelt — via monkeypatch em requests.get (sem rede)
# ---------------------------------------------------------------------------
def test_fetch_gdelt_normaliza(monkeypatch):
    payload = {
        "articles": [
            {
                "title": "Geopolitical risk rises",
                "url": "http://g/1",
                "domain": "reuters.com",
                "seendate": "20260602T134000Z",
            },
            {"title": "", "url": "", "domain": "x.com"},  # vazio -> descartado
        ]
    }
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(payload)

    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(fake_get)}))

    out = fetch_gdelt("oil OR fed", timemins=30, max_records=10)
    assert len(out) == 1
    assert out[0].title == "Geopolitical risk rises"
    assert out[0].url == "http://g/1"
    assert out[0].source == "gdelt:reuters.com"
    assert out[0].published == datetime(2026, 6, 2, 13, 40, tzinfo=timezone.utc)
    # Confere que montou a query corretamente para a DOC API.
    assert captured["url"] == ns.GDELT_DOC_API
    assert captured["params"]["format"] == "json"
    assert captured["params"]["query"] == "oil OR fed"
    assert captured["params"]["timespan"] == "30min"


def test_fetch_gdelt_erro_de_rede_retorna_vazio(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise RuntimeError("timeout")

    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(boom)}))
    assert fetch_gdelt("oil") == []


def test_fetch_gdelt_json_invalido_retorna_vazio(monkeypatch):
    class BadResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("nao e json")

    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(lambda *a, **k: BadResp())}))
    assert fetch_gdelt("oil") == []


def test_fetch_gdelt_sem_requests(monkeypatch):
    monkeypatch.setattr(ns, "requests", None)
    assert fetch_gdelt("oil") == []


# ---------------------------------------------------------------------------
# fetch_finnhub_calendar — via monkeypatch em requests.get (sem rede)
# ---------------------------------------------------------------------------
def test_fetch_finnhub_calendar_normaliza(monkeypatch):
    payload = {
        "economicCalendar": [
            {"event": "NFP", "impact": "high", "time": "2026-06-05 12:30:00"},
            {"event": "CPI", "impact": "high", "time": "2026-06-10 12:30:00"},
        ]
    }
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(payload)

    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(fake_get)}))

    eventos = fetch_finnhub_calendar("CHAVE123")
    assert len(eventos) == 2
    assert eventos[0]["event"] == "NFP"
    assert captured["url"] == ns.FINNHUB_ECON_CALENDAR
    assert captured["params"]["token"] == "CHAVE123"


def test_fetch_finnhub_calendar_sem_chave(monkeypatch):
    """api_key vazio -> [] (e nem chega a tocar em requests)."""
    # mesmo com requests "presente", sem chave deve retornar [].
    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(lambda *a, **k: _FakeResponse({}))}))
    assert fetch_finnhub_calendar("") == []


def test_fetch_finnhub_calendar_erro_de_rede(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise RuntimeError("conexao recusada")

    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(boom)}))
    assert fetch_finnhub_calendar("CHAVE") == []


def test_fetch_finnhub_calendar_resposta_inesperada(monkeypatch):
    """economicCalendar que não é lista -> []."""
    payload = {"economicCalendar": "oops"}
    monkeypatch.setattr(ns, "requests", type("RQ", (), {"get": staticmethod(lambda *a, **k: _FakeResponse(payload))}))
    assert fetch_finnhub_calendar("CHAVE") == []


def test_fetch_finnhub_calendar_sem_requests(monkeypatch):
    monkeypatch.setattr(ns, "requests", None)
    assert fetch_finnhub_calendar("CHAVE") == []
