"""Testes do motor de viés por notícias (smarttrader/news_ai.py).

Valida o CONTRATO do Bias e o comportamento do stub:
  * bias sempre em {-1, 0, 1} e confidence em [0, 1];
  * stub retorna NEUTRO (bias=0, confidence=0);
  * fail-safe: qualquer exceção interna -> NEUTRO com stale=True (nunca derruba
    o trader);
  * override_bias (modo de teste) funciona, tanto Bias pronto quanto callable.

Rodar: pytest tests/test_news_ai.py
"""

import pytest

from smarttrader.news_ai import Bias, NewsBiasEngine


# ---------------------------------------------------------------------------
# Contrato do Bias / stub neutro
# ---------------------------------------------------------------------------
def test_stub_retorna_neutro():
    """Sem nada plugado, o motor devolve viés NEUTRO honesto."""
    eng = NewsBiasEngine()
    b = eng.get_bias("EURUSD")

    assert isinstance(b, Bias)
    assert b.symbol == "EURUSD"
    assert b.bias == 0
    assert b.confidence == 0.0
    assert b.blocked is False
    assert b.stale is False
    assert "stub" in b.rationale.lower()


def test_contrato_bias_dominio():
    """bias ∈ {-1,0,1} e confidence ∈ [0,1] para vários símbolos."""
    eng = NewsBiasEngine()
    for sym in ("EURUSD", "USDCAD", "XAUUSD", "GBPJPY"):
        b = eng.get_bias(sym)
        assert b.bias in (-1, 0, 1)
        assert 0.0 <= b.confidence <= 1.0
        assert b.symbol == sym


# ---------------------------------------------------------------------------
# Modo defensivo: janela de evento de alto impacto -> blocked
# ---------------------------------------------------------------------------
def test_janela_alto_impacto_bloqueia():
    """Com calendário dizendo 'em janela', get_bias devolve blocked=True e neutro."""
    eng = NewsBiasEngine(high_impact_calendar=lambda now: True)
    b = eng.get_bias("EURUSD")
    assert b.blocked is True
    assert b.bias == 0
    assert b.confidence == 0.0


def test_fora_da_janela_nao_bloqueia():
    eng = NewsBiasEngine(high_impact_calendar=lambda now: False)
    b = eng.get_bias("EURUSD")
    assert b.blocked is False
    assert b.bias == 0


# ---------------------------------------------------------------------------
# Fail-safe: exceção interna -> neutro + stale=True
# ---------------------------------------------------------------------------
def test_failsafe_calendario_que_lanca():
    """Se o calendário (dependência interna) lança, NÃO derruba: neutro + stale."""
    def boom(now):
        raise RuntimeError("falha simulada no calendario")

    eng = NewsBiasEngine(high_impact_calendar=boom)
    b = eng.get_bias("EURUSD")

    assert b.bias == 0
    assert b.confidence == 0.0
    assert b.stale is True
    assert "fail-safe" in b.rationale.lower()


def test_failsafe_override_que_lanca():
    """Override callable que lança também cai no fail-safe (stale=True)."""
    def boom(symbol):
        raise ValueError("erro no override")

    eng = NewsBiasEngine(override_bias=boom)
    b = eng.get_bias("USDCAD")

    assert b.bias == 0
    assert b.stale is True
    assert b.symbol == "USDCAD"


# ---------------------------------------------------------------------------
# override_bias (modo de teste determinístico)
# ---------------------------------------------------------------------------
def test_override_bias_objeto_pronto():
    """override_bias como Bias pronto é devolvido como está."""
    fixo = Bias(symbol="USDCAD", bias=-1, confidence=0.62,
                rationale="teste deterministico")
    eng = NewsBiasEngine(override_bias=fixo)
    b = eng.get_bias("USDCAD")

    assert b is fixo
    assert b.bias == -1
    assert b.confidence == pytest.approx(0.62)


def test_override_bias_preenche_symbol_vazio():
    """Bias com symbol vazio recebe o símbolo solicitado."""
    fixo = Bias(symbol="", bias=1, confidence=0.5)
    eng = NewsBiasEngine(override_bias=fixo)
    b = eng.get_bias("XAUUSD")
    assert b.symbol == "XAUUSD"
    assert b.bias == 1


def test_override_bias_callable():
    """override_bias como callable fn(symbol) -> Bias é chamado por símbolo."""
    def gerador(symbol):
        return Bias(symbol=symbol, bias=1, confidence=0.8, rationale="callable")

    eng = NewsBiasEngine(override_bias=gerador)
    b = eng.get_bias("GBPUSD")

    assert b.symbol == "GBPUSD"
    assert b.bias == 1
    assert b.confidence == pytest.approx(0.8)
    # Continua respeitando o contrato.
    assert b.bias in (-1, 0, 1)
    assert 0.0 <= b.confidence <= 1.0
