"""Testes do pipeline ao vivo: bias_from_live_news (RSS/GDELT -> direção).

Usa monkeypatch para NÃO bater na rede: injeta notícias falsas em
``smarttrader.news_sources`` e valida a direção resultante e os fail-safes.
"""
from __future__ import annotations

import smarttrader.news_sources as ns
from smarttrader.news_ai import Bias, NewsBiasEngine


def _fake_items(titles):
    return [ns.NewsItem(title=t, summary="", url=f"http://x/{i}", source="fake",
                        published=None) for i, t in enumerate(titles)]


def test_live_crise_petroleo_usdcad(monkeypatch):
    """Notícias ao vivo de crise no petróleo -> USDCAD não pode dar COMPRA."""
    monkeypatch.setattr(ns, "fetch_rss",
                        lambda *a, **k: _fake_items(
                            ["Oil prices spike after OPEC supply cut amid war"]))
    monkeypatch.setattr(ns, "fetch_gdelt", lambda *a, **k: [])
    v = NewsBiasEngine().bias_from_live_news("USDCAD")
    assert isinstance(v, Bias)
    assert v.bias in (-1, 0)
    assert 0.0 <= v.confidence <= 1.0


def test_live_sem_noticia_neutro(monkeypatch):
    """Sem notícia relevante -> NEUTRO (não stale: foi um resultado válido)."""
    monkeypatch.setattr(ns, "fetch_rss", lambda *a, **k: [])
    monkeypatch.setattr(ns, "fetch_gdelt", lambda *a, **k: [])
    v = NewsBiasEngine().bias_from_live_news("EURUSD")
    assert v.bias == 0


def test_live_failsafe_rede_quebrada(monkeypatch):
    """Se a busca lança exceção -> fail-safe: neutro com stale=True."""
    def boom(*a, **k):
        raise RuntimeError("rede caiu")
    monkeypatch.setattr(ns, "fetch_rss", boom)
    v = NewsBiasEngine().bias_from_live_news("USDCAD")
    assert v.bias == 0 and v.stale is True


def test_live_filtra_irrelevante(monkeypatch):
    """Notícia sem relação com o símbolo é filtrada -> NEUTRO."""
    monkeypatch.setattr(ns, "fetch_rss",
                        lambda *a, **k: _fake_items(["Local sports team wins title"]))
    monkeypatch.setattr(ns, "fetch_gdelt", lambda *a, **k: [])
    v = NewsBiasEngine().bias_from_live_news("USOIL")
    assert v.bias == 0
