"""Testes do caminho usável da IA: bias_from_headlines (manchetes -> direção).

Não dependem de transformers/GPU — exercitam a combinação news_mapper + Bias.
"""
from __future__ import annotations

from smarttrader.news_ai import Bias, NewsBiasEngine


def test_crise_petroleo_usdcad_vende():
    """Crise no petróleo -> USDCAD tende a VENDA (CAD forte)."""
    eng = NewsBiasEngine()
    manchetes = ["Oil prices spike after OPEC supply cut amid Middle East war"]
    v = eng.bias_from_headlines("USDCAD", manchetes)
    assert isinstance(v, Bias)
    assert v.bias in (-1, 0)          # não pode ser COMPRA nesse cenário
    assert 0.0 <= v.confidence <= 1.0


def test_crise_petroleo_ouro_compra():
    """Risk-off + petróleo -> Ouro (XAUUSD) tende a COMPRA."""
    eng = NewsBiasEngine()
    manchetes = ["Crude surges as conflict and recession fears grip markets"]
    v = eng.bias_from_headlines("XAUUSD", manchetes)
    assert v.bias in (1, 0)
    assert 0.0 <= v.confidence <= 1.0


def test_sem_tema_neutro():
    """Manchete irrelevante -> NEUTRO."""
    eng = NewsBiasEngine()
    v = eng.bias_from_headlines("EURUSD", ["Company X announces new logo design"])
    assert v.bias == 0


def test_scorer_reforca_confianca():
    """Um scorer fake (avg_confidence) deve ajustar a confiança sem quebrar."""
    class FakeScorer:
        def avg_confidence(self, textos):
            return 1.0  # sentimento máximo
    eng = NewsBiasEngine()
    manchetes = ["Oil prices spike after OPEC supply cut amid war"]
    v = eng.bias_from_headlines("USDCAD", manchetes, scorer=FakeScorer())
    assert 0.0 <= v.confidence <= 1.0


def test_failsafe_scorer_quebrado():
    """Se o scorer lança exceção -> fail-safe: Bias neutro com stale=True."""
    class BrokenScorer:
        def avg_confidence(self, textos):
            raise RuntimeError("boom")
    eng = NewsBiasEngine()
    v = eng.bias_from_headlines("USDCAD", ["Oil spikes"], scorer=BrokenScorer())
    assert v.bias == 0 and v.stale is True
