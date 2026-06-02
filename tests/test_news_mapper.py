"""Testes do mapeador macro->direção (smarttrader/news_mapper.py).

Cobre:
  * detect_themes acha "oil" em manchete de OPEP;
  * petróleo em alta forte (sem risk_off) -> USDCAD bias -1 (CAD forte);
  * petróleo↑ E risk_off forte simultâneos -> conflito -> USDCAD NEUTRO (0)
    com justificativa citando o conflito;
  * XAUUSD em risk_off -> bias +1;
  * símbolo sem exposição / sem temas -> 0;
  * invariantes de contrato: confidence em [0,1] e bias em {-1,0,1}.

Offline, sem rede. Rodar: pytest tests/test_news_mapper.py
"""

import pytest

from smarttrader.news_mapper import (
    SYMBOL_EXPOSURE,
    ThemeSignal,
    bias_for_symbol,
    detect_themes,
)


# ---------------------------------------------------------------------------
# detect_themes
# ---------------------------------------------------------------------------
def test_detect_oil_em_manchete_opec():
    """'Oil prices spike after OPEC cut' deve disparar o tema 'oil'."""
    themes = detect_themes(["Oil prices spike after OPEC cut"])
    nomes = {t.theme for t in themes}
    assert "oil" in nomes


def test_detect_oil_sentiment_alta():
    """'spike' indica intensificacao -> sentiment +1 e strength em (0,1]."""
    themes = detect_themes(["Oil prices spike after OPEC cut, crude soars"])
    oil = next(t for t in themes if t.theme == "oil")
    assert oil.sentiment == 1
    assert 0.0 < oil.strength <= 1.0


def test_detect_oil_sentiment_baixa():
    """'glut'/'plunge' indicam queda -> sentiment -1."""
    themes = detect_themes(["Oil glut sends crude prices to plunge"])
    oil = next(t for t in themes if t.theme == "oil")
    assert oil.sentiment == -1


def test_detect_sem_texto_retorna_vazio():
    """Sem texto util, nenhum tema."""
    assert detect_themes([]) == []
    assert detect_themes(["", "   "]) == []


# ---------------------------------------------------------------------------
# bias_for_symbol — caso petróleo em alta forte (sem risk_off)
# ---------------------------------------------------------------------------
def test_petroleo_alta_forte_usdcad_vende():
    """Petróleo↑ forte sozinho fortalece o CAD -> USDCAD cai (bias -1)."""
    themes = [ThemeSignal(theme="oil", sentiment=1, strength=0.9)]
    bias, conf, rationale = bias_for_symbol("USDCAD", themes)
    assert bias == -1
    assert 0.0 <= conf <= 1.0
    assert conf > 0.0
    assert isinstance(rationale, str) and rationale


# ---------------------------------------------------------------------------
# bias_for_symbol — FORÇAS CONFLITANTES (o caso central do IA_NOTICIAS.md)
# ---------------------------------------------------------------------------
def test_petroleo_e_riskoff_simultaneos_usdcad_neutro():
    """Petróleo↑ (CAD+ -> USDCAD↓) x safe-haven USD (USDCAD↑) se anulam.

    Resultado esperado: NEUTRO (0), confianca baixa, e rationale citando o
    conflito.
    """
    themes = [
        ThemeSignal(theme="oil", sentiment=1, strength=0.85),
        ThemeSignal(theme="risk_off", sentiment=1, strength=0.85),
    ]
    bias, conf, rationale = bias_for_symbol("USDCAD", themes)
    assert bias == 0
    assert 0.0 <= conf <= 1.0
    # justificativa deve mencionar o conflito
    assert "conflitante" in rationale.lower() or "anula" in rationale.lower()


# ---------------------------------------------------------------------------
# bias_for_symbol — XAUUSD em risk_off
# ---------------------------------------------------------------------------
def test_xauusd_riskoff_compra():
    """Risk-off liga corrida pro ouro -> XAUUSD sobe (bias +1)."""
    themes = [ThemeSignal(theme="risk_off", sentiment=1, strength=0.8)]
    bias, conf, rationale = bias_for_symbol("XAUUSD", themes)
    assert bias == 1
    assert 0.0 <= conf <= 1.0
    assert conf > 0.0


# ---------------------------------------------------------------------------
# Sem exposição / sem temas -> neutro
# ---------------------------------------------------------------------------
def test_simbolo_sem_exposicao_ao_tema():
    """USOIL/WTI nao tem coeficiente para 'rates_hawkish' -> neutro."""
    themes = [ThemeSignal(theme="rates_hawkish", sentiment=1, strength=0.9)]
    bias, conf, rationale = bias_for_symbol("USOIL", themes)
    assert bias == 0
    assert conf == 0.0


def test_sem_temas_neutro():
    """Lista de temas vazia -> neutro com confianca zero."""
    bias, conf, rationale = bias_for_symbol("EURUSD", [])
    assert bias == 0
    assert conf == 0.0


def test_simbolo_desconhecido_neutro():
    """Simbolo fora do mapa de exposicao -> neutro honesto."""
    themes = [ThemeSignal(theme="oil", sentiment=1, strength=0.9)]
    bias, conf, rationale = bias_for_symbol("NZDCHF", themes)
    assert bias == 0
    assert conf == 0.0


# ---------------------------------------------------------------------------
# Invariantes de contrato
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("symbol", list(SYMBOL_EXPOSURE.keys()))
def test_contrato_bias_e_confidence(symbol):
    """Para todo simbolo conhecido: bias em {-1,0,1} e confidence em [0,1]."""
    cenarios = [
        [],
        [ThemeSignal(theme="oil", sentiment=1, strength=1.0)],
        [ThemeSignal(theme="oil", sentiment=-1, strength=1.0)],
        [ThemeSignal(theme="risk_off", sentiment=1, strength=1.0)],
        [ThemeSignal(theme="risk_on", sentiment=1, strength=0.5)],
        [
            ThemeSignal(theme="oil", sentiment=1, strength=0.9),
            ThemeSignal(theme="risk_off", sentiment=1, strength=0.9),
            ThemeSignal(theme="rates_hawkish", sentiment=1, strength=0.7),
        ],
    ]
    for themes in cenarios:
        bias, conf, rationale = bias_for_symbol(symbol, themes)
        assert bias in (-1, 0, 1)
        assert 0.0 <= conf <= 1.0
        assert isinstance(rationale, str)


def test_usoil_segue_petroleo():
    """USOIL deve seguir o tema oil 1:1 -> petróleo↑ -> bias +1."""
    themes = [ThemeSignal(theme="oil", sentiment=1, strength=0.9)]
    bias, conf, _ = bias_for_symbol("USOIL", themes)
    assert bias == 1
    assert conf > 0.0
