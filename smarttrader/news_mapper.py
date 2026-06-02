"""Mapeador macro -> direção (camada TRANSPARENTE / baseline por regras).

Esta é a versão EXPLICÁVEL e determinística do raciocínio que o LLM fará depois
(ver smarttrader/news_ai.py e docs/IA_NOTICIAS.md). Em vez de chamar um modelo,
ela aplica REGRAS macroeconômicas auditáveis:

    1. Detecta TEMAS econômicos em textos de notícia (oil, rates_hawkish,
       risk_off, risk_on, ...), cada um com sentimento (+1/-1) e força (0..1).
    2. Mapeia cada tema para um VIÉS direcional por símbolo via COEFICIENTES de
       exposição (positivo = tema↑ empurra o símbolo↑; negativo = empurra↓).
    3. Soma as forças (coef × sentimento × força) e, crucialmente, trata FORÇAS
       CONFLITANTES: quando elas se cancelam, devolve NEUTRO com confiança baixa
       e uma justificativa que explica o conflito.

------------------------------------------------------------------------------
HONESTIDADE OBRIGATÓRIA (não é bola de cristal):
    Isto é um BASELINE HEURÍSTICO, não previsão garantida. Serve para dois fins:
        * baseline: um piso explicável contra o qual comparar o LLM;
        * sanity-check: se o LLM discordar fortemente desta regra simples, é
          sinal de alerta para revisar o raciocínio.
    Notícia "óbvia" já está precificada em segundos. Estas regras capturam apenas
    a direção macro de 1ª ordem; não modelam timing, magnitude nem o que já está
    no preço. Em ambiguidade o comportamento correto é dizer "não sei" (NEUTRO),
    exatamente como exige IA_NOTICIAS.md ("se elas se cancelam -> NEUTRO com
    confiança baixa").
------------------------------------------------------------------------------

Puro Python, SEM rede, totalmente testável.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

# Logger do módulo (mensagens em português). Quem importar pode configurar nível.
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Estrutura de sinal de tema
# ----------------------------------------------------------------------------
@dataclass
class ThemeSignal:
    """Sinal de um tema macro detectado nas notícias.

    Campos:
        theme:     nome do tema (chave de THEME_KEYWORDS), ex.: "oil".
        sentiment: +1 = tema INTENSIFICANDO / em alta (ex.: petróleo subindo,
                   guerra escalando); -1 = tema EM BAIXA / arrefecendo (ex.:
                   excesso de oferta de petróleo, distensão).
        strength:  intensidade 0..1, proporcional à frequência/insistência do
                   tema nos textos (quanto mais a notícia bate na tecla, maior).
    """

    theme: str
    sentiment: int  # +1 (intensificando) / -1 (arrefecendo)
    strength: float  # 0..1


# ----------------------------------------------------------------------------
# THEME_KEYWORDS — temas macro e palavras-chave que os disparam
# ----------------------------------------------------------------------------
# Observação: a detecção é case-insensitive e por substring de palavra. Mantemos
# termos em inglês (manchetes globais) e alguns em português/sem acento.
THEME_KEYWORDS: dict[str, list[str]] = {
    # Petróleo / energia. Núcleo do exemplo "crise no petróleo" do IA_NOTICIAS.md.
    "oil": [
        "oil", "petroleum", "petroleo", "petróleo", "opec", "opep",
        "crude", "brent", "wti", "barrel", "barril",
    ],
    # Política monetária restritiva (juros para cima / aperto / inflação subindo).
    # Tende a fortalecer a moeda do banco central (foco aqui: USD).
    "rates_hawkish": [
        "rate hike", "rate hikes", "hike rates", "raise rates", "tightening",
        "hawkish", "inflation surge", "inflation jump", "cpi beat",
        "higher for longer",
    ],
    # Política monetária frouxa (cortes / afrouxamento / inflação cedendo).
    # Tende a enfraquecer a moeda do banco central (foco aqui: USD).
    "rates_dovish": [
        "rate cut", "rate cuts", "cut rates", "easing", "dovish",
        "stimulus", "quantitative easing", "inflation cooling", "disinflation",
    ],
    # Aversão a risco / safe-haven. Liga demanda por USD e OURO (XAU).
    "risk_off": [
        "war", "guerra", "crisis", "crise", "conflict", "conflito",
        "recession", "recessao", "recessão", "crash", "selloff", "sell-off",
        "panic", "panico", "pânico", "turmoil", "geopolitical", "geopolitico",
        "geopolítico", "sanctions", "sancoes", "sanções", "default",
    ],
    # Apetite por risco / otimismo. Pressiona safe-havens (USD/OURO) para baixo.
    "risk_on": [
        "rally", "optimism", "otimismo", "growth beat", "soft landing",
        "risk appetite", "record high", "bull market", "recovery", "rebound",
    ],
}

# Palavras que indicam o tema SUBINDO/INTENSIFICANDO (sentimento +1) e CAINDO
# (sentimento -1). Usadas por detect_themes para inferir o sinal do tema.
# Heurística: procuramos esses gatilhos perto/junto do texto do tema.
_UP_WORDS = [
    "surge", "surges", "spike", "spikes", "soar", "soars", "soaring", "jump",
    "jumps", "rise", "rises", "rising", "rally", "rallies", "climb", "climbs",
    "gain", "gains", "escalate", "escalates", "escalating", "boost", "boosts",
    "high", "higher", "up", "alta", "sobe", "subindo", "disparou", "dispara",
]
_DOWN_WORDS = [
    "plunge", "plunges", "plummet", "plummets", "drop", "drops", "fall",
    "falls", "falling", "slump", "slumps", "glut", "oversupply", "crash",
    "crashes", "slide", "slides", "tumble", "tumbles", "ease", "eases",
    "easing", "cool", "cools", "cooling", "low", "lower", "down", "queda",
    "cai", "caindo", "despencou", "despenca", "recuo",
]


# ----------------------------------------------------------------------------
# detect_themes — extrai ThemeSignal dos textos
# ----------------------------------------------------------------------------
def detect_themes(texts: list[str]) -> list[ThemeSignal]:
    """Detecta os temas presentes em ``texts`` (case-insensitive).

    Heurísticas (comentadas para serem auditáveis):

      * FORÇA (strength): proporcional à FREQUÊNCIA do tema. Contamos quantos
        gatilhos de palavra-chave do tema aparecem no conjunto de textos e
        normalizamos de forma saturante (1 hit já dá força razoável; muitos hits
        saturam perto de 1). Isto reflete "quanto a notícia bate na tecla".

      * SENTIMENTO (sentiment): inferido por palavras de direção perto do tema.
        - Termos de alta ("surge", "spike", "soar", "alta") -> +1.
        - Termos de baixa ("plunge", "glut", "plummet", "queda") -> -1.
        Para o tema "oil", "oil surge/spike" -> +1; "oil glut/plunge" -> -1.
        Para temas que JÁ SÃO direcionais por natureza (risk_off, risk_on,
        rates_hawkish, rates_dovish), o simples aparecimento do tema indica que
        ele está intensificando, então o padrão é +1 (a menos que haja termos de
        baixa dominando, ex.: "recession fears EASE").

    Honestidade: é um detector de palavra-chave simples, NÃO entende contexto
    nem negação complexa ("not a recession"). É de propósito: baseline auditável.
    """
    # Junta tudo num único texto minúsculo para busca por substring.
    blob = " \n ".join(t for t in texts if t).lower()
    if not blob.strip():
        logger.debug("detect_themes: nenhum texto util recebido")
        return []

    signals: list[ThemeSignal] = []

    for theme, keywords in THEME_KEYWORDS.items():
        # --- Frequência: conta ocorrências de cada palavra-chave do tema. -----
        hits = 0
        for kw in keywords:
            # Busca por substring simples (case-insensitive já que blob é lower).
            # count() pega todas as ocorrências; multi-palavra ("rate hike") ok.
            hits += blob.count(kw)
        if hits == 0:
            continue  # tema ausente

        # --- Força saturante: 1 -> ~0.5, 2 -> ~0.67, 3 -> 0.75, ... -> ~1.0.
        # Fórmula hits/(hits+1) é monotônica, saturante e fácil de explicar.
        strength = hits / (hits + 1.0)

        # --- Sentimento: olha termos de alta/baixa no blob inteiro. -----------
        up_count = sum(blob.count(w) for w in _UP_WORDS)
        down_count = sum(blob.count(w) for w in _DOWN_WORDS)

        if up_count > down_count:
            sentiment = 1
        elif down_count > up_count:
            sentiment = -1
        else:
            # Empate de direção. Para temas naturalmente direcionais (risk_off,
            # risk_on, rates_*), o mero aparecimento já significa intensificação:
            # default +1. Para "oil" sem pista de direção, ficamos neutros via
            # sentiment 0 (não sabemos se subiu ou caiu).
            if theme == "oil":
                sentiment = 0
            else:
                sentiment = 1

        logger.debug(
            "detect_themes: tema=%s hits=%d strength=%.2f sentiment=%+d "
            "(up=%d down=%d)",
            theme, hits, strength, sentiment, up_count, down_count,
        )
        signals.append(ThemeSignal(theme=theme, sentiment=sentiment,
                                    strength=round(strength, 4)))

    return signals


# ----------------------------------------------------------------------------
# SYMBOL_EXPOSURE — coeficiente de exposição de cada símbolo a cada tema
# ----------------------------------------------------------------------------
# Convenção: coeficiente POSITIVO = "tema subindo (sentiment +1) empurra o PREÇO
# do símbolo para CIMA"; NEGATIVO = empurra para BAIXO. Magnitude ~ quão forte é
# o canal macro (0..1, valores aproximados/qualitativos).
#
# Lembrete dos pares (preço = quanto da 2ª moeda por 1 da 1ª):
#   EURUSD: USD↑ -> EURUSD↓.   GBPUSD: USD↑ -> GBPUSD↓.
#   USDJPY: USD↑ -> USDJPY↑.   USDCAD: USD↑ -> USDCAD↑ ; CAD↑ -> USDCAD↓.
#   XAUUSD: ouro em USD.       USOIL/WTI: preço do petróleo em si.
#
# As FORÇAS CONFLITANTES do IA_NOTICIAS.md ("crise no petróleo") aparecem em
# USDCAD: tema "oil" tem coeficiente NEGATIVO (petróleo↑ fortalece CAD ->
# USDCAD↓), MAS o tema "risk_off" tem coeficiente POSITIVO (safe-haven liga USD
# -> USDCAD↑). Quando ambos aparecem fortes, as forças se anulam -> NEUTRO.
SYMBOL_EXPOSURE: dict[str, dict[str, float]] = {
    # ---- EURUSD: principalmente um trade de USD. -------------------------
    "EURUSD": {
        # USD hawkish fortalece USD -> EURUSD cai. Coef negativo.
        "rates_hawkish": -0.8,
        # USD dovish enfraquece USD -> EURUSD sobe. Coef positivo.
        "rates_dovish": 0.8,
        # Risk-off -> demanda por USD (safe-haven) -> EURUSD cai. Negativo.
        "risk_off": -0.5,
        # Risk-on -> USD safe-haven perde força -> EURUSD sobe. Positivo.
        "risk_on": 0.4,
        # Petróleo não tem canal direto forte sobre EURUSD (zona euro importa,
        # mas efeito de 2ª ordem). Mantemos pequeno e negativo (petróleo caro
        # piora termos de troca da zona euro). Honestamente fraco.
        "oil": -0.15,
    },
    # ---- GBPUSD: análogo a EURUSD (trade de USD). ------------------------
    "GBPUSD": {
        "rates_hawkish": -0.8,
        "rates_dovish": 0.8,
        "risk_off": -0.5,   # GBP é moeda de risco; risk-off derruba GBPUSD.
        "risk_on": 0.4,
        "oil": -0.1,        # UK importadora líquida; efeito fraco.
    },
    # ---- USDJPY: USD na ponta e JPY como safe-haven na outra. ------------
    "USDJPY": {
        # USD hawkish + diferencial de juros -> USDJPY sobe forte. Positivo.
        "rates_hawkish": 0.8,
        "rates_dovish": -0.8,
        # Risk-off: JPY também é safe-haven e costuma SUPERAR o USD em pânico
        # forte (carry unwind) -> USDJPY tende a CAIR. Coef negativo.
        "risk_off": -0.5,
        "risk_on": 0.4,     # risk-on/carry favorece USDJPY (vende JPY).
        # Japão importa quase todo o petróleo: petróleo↑ piora conta corrente do
        # JPY -> JPY enfraquece -> USDJPY sobe. Coef positivo (moderado).
        "oil": 0.3,
    },
    # ---- USDCAD: o caso clássico de FORÇAS CONFLITANTES. -----------------
    "USDCAD": {
        # PETRÓLEO: Canadá é grande exportador. Petróleo↑ fortalece o CAD ->
        # USDCAD CAI. Por isso o coeficiente é NEGATIVO (canal forte, ~-0.7).
        # (IA_NOTICIAS.md: "Petróleo sobe -> CAD fortalece -> USDCAD cai".)
        "oil": -0.7,
        # SAFE-HAVEN: crise/guerra liga demanda por USD -> empurra USDCAD pra
        # CIMA. Coeficiente POSITIVO. É a força que CONFLITA com o petróleo
        # numa "crise no petróleo" geopolítica (petróleo sobe E risk-off sobe).
        "risk_off": 0.6,
        "risk_on": -0.4,    # risk-on tira o prêmio de safe-haven do USD.
        # USD hawkish fortalece USD -> USDCAD sobe. Positivo. (BoC vs Fed é
        # mais simétrico, então um pouco menor que em EURUSD.)
        "rates_hawkish": 0.5,
        "rates_dovish": -0.5,
    },
    # ---- XAUUSD: ouro. Safe-haven por excelência. ------------------------
    "XAUUSD": {
        # Risk-off -> corrida pro ouro -> XAUUSD SOBE. Coef POSITIVO (forte).
        # (IA_NOTICIAS.md: "crise geopolítica ... e ouro pra cima".)
        "risk_off": 0.8,
        "risk_on": -0.4,    # apetite por risco tira brilho do ouro.
        # Juros altos (hawkish) sobem o custo de oportunidade de segurar ouro
        # (não paga juros) e fortalecem o USD -> XAUUSD CAI. Coef negativo.
        "rates_hawkish": -0.6,
        "rates_dovish": 0.6,
        # Petróleo↑ costuma vir junto de medo inflacionário/geopolítico, que dá
        # algum suporte ao ouro. Canal fraco e positivo.
        "oil": 0.2,
    },
    # ---- USOIL / WTI: o próprio petróleo. --------------------------------
    # Aqui o tema "oil" mapeia 1:1 no preço (coef +1: petróleo↑ -> USOIL↑).
    "USOIL": {
        "oil": 1.0,
        # Risk-off geopolítico (guerra em região produtora) tende a sustentar o
        # petróleo (prêmio de risco de oferta) -> positivo, moderado.
        "risk_off": 0.3,
        # Risk-on/crescimento -> mais demanda por energia -> petróleo sobe.
        "risk_on": 0.3,
    },
}
# Alias: muitas corretoras chamam o WTI de "WTI". Aponta para a mesma exposição.
SYMBOL_EXPOSURE["WTI"] = SYMBOL_EXPOSURE["USOIL"]


# Limiar mínimo de confiança para SAIR do neutro. Abaixo disso (forças fracas ou
# que se cancelam) devolvemos bias 0 — o sistema "diz que não sabe" em vez de
# inventar convicção (princípio central do IA_NOTICIAS.md).
MIN_CONFIDENCE = 0.15

# Fator de normalização da soma ponderada -> confiança. A soma bruta pode passar
# de 1 quando vários temas fortes alinham; dividimos por este valor e saturamos
# em 1. Escolhido para que um único canal forte (coef ~0.7, strength ~0.6,
# sentiment 1 => ~0.42) já dê confiança relevante (~0.42/0.8 ≈ 0.53).
_CONF_SCALE = 0.8


# ----------------------------------------------------------------------------
# bias_for_symbol — combina temas -> viés direcional do símbolo
# ----------------------------------------------------------------------------
def bias_for_symbol(symbol: str,
                    themes: list[ThemeSignal]) -> tuple[int, float, str]:
    """Calcula o viés direcional de ``symbol`` dado os temas detectados.

    Mecânica:
        net = Σ ( coef[símbolo][tema] × sentiment × strength )   sobre os temas

      * net > 0 empurra o PREÇO para cima (candidato a bias +1);
      * net < 0 empurra para baixo (candidato a bias -1);
      * |net| pequeno -> NEUTRO (forças fracas ou que se cancelam).

    REGRA-CHAVE (forças conflitantes, IA_NOTICIAS.md):
        Mesmo que algum tema isolado seja forte, se as contribuições se ANULAM
        (a soma fica perto de zero enquanto havia forças opostas relevantes),
        devolvemos NEUTRO (0) com confiança baixa e uma justificativa que cita o
        conflito — exatamente o caso "petróleo↑ favorece CAD (USDCAD↓) mas
        safe-haven liga USD (USDCAD↑)". Usamos MIN_CONFIDENCE como limiar para
        sair do neutro.

    Retorna: (bias ∈ {-1,0,1}, confidence ∈ [0,1], rationale em português).
    """
    exposure = SYMBOL_EXPOSURE.get(symbol)
    if exposure is None:
        msg = f"{symbol}: sem mapa de exposicao macro; sem opiniao (neutro)."
        logger.debug(msg)
        return 0, 0.0, msg

    if not themes:
        msg = f"{symbol}: nenhum tema macro detectado; neutro."
        logger.debug(msg)
        return 0, 0.0, msg

    net = 0.0
    # Guardamos contribuições para (a) detectar conflito e (b) montar a
    # justificativa. contributions: lista de (tema, contrib, coef).
    contributions: list[tuple[str, float, float]] = []
    pos_force = 0.0  # soma das contribuições que empurram pra CIMA
    neg_force = 0.0  # soma (em módulo) das que empurram pra BAIXO

    for ts in themes:
        coef = exposure.get(ts.theme)
        if coef is None:
            continue  # símbolo não tem exposição a este tema -> ignora
        contrib = coef * ts.sentiment * ts.strength
        if contrib == 0:
            continue
        net += contrib
        contributions.append((ts.theme, contrib, coef))
        if contrib > 0:
            pos_force += contrib
        else:
            neg_force += -contrib

    if not contributions:
        msg = (f"{symbol}: temas detectados nao afetam este simbolo "
               f"(sem exposicao relevante); neutro.")
        logger.debug(msg)
        return 0, 0.0, msg

    # Magnitude bruta total das forças (sem cancelamento), p/ medir conflito.
    total_force = pos_force + neg_force
    # Confiança candidata: força LÍQUIDA normalizada e saturada em [0,1].
    confidence = min(abs(net) / _CONF_SCALE, 1.0)

    # --- Detecção de CONFLITO -------------------------------------------------
    # Há conflito quando existem forças relevantes nos DOIS sentidos e o líquido
    # ficou pequeno em relação ao total (uma anulou boa parte da outra).
    forcas_opostas = pos_force > 0 and neg_force > 0
    # "menor força" representa pelo menos ~35% do total -> oposição relevante
    # (e não um ruidinho desprezível).
    oposicao_relevante = (min(pos_force, neg_force) / total_force) >= 0.35

    if forcas_opostas and oposicao_relevante and confidence < MIN_CONFIDENCE:
        # Caso "crise no petróleo": forças se cancelam -> NEUTRO honesto.
        detalhe = _descreve_conflito(contributions)
        msg = (f"{symbol}: forcas conflitantes se anulam ({detalhe}); "
               f"sem direcao clara -> NEUTRO (confianca baixa {confidence:.2f}).")
        logger.info(msg)
        return 0, round(confidence, 4), msg

    # --- Confiança fraca (mesmo sem conflito): também NEUTRO. -----------------
    if confidence < MIN_CONFIDENCE:
        msg = (f"{symbol}: forca macro liquida fraca ({net:+.2f}); "
               f"abaixo do limiar -> NEUTRO.")
        logger.debug(msg)
        return 0, round(confidence, 4), msg

    # --- Direção definida -----------------------------------------------------
    bias = 1 if net > 0 else -1
    direcao = "ALTA" if bias > 0 else "BAIXA"
    detalhe = _descreve_contribuicoes(contributions)
    aviso_conflito = ""
    if forcas_opostas and oposicao_relevante:
        # Há oposição relevante, mas uma força DOMINOU: deixamos explícito.
        aviso_conflito = " (havia forcas opostas, mas uma dominou)"
    msg = (f"{symbol}: vies de {direcao} (net={net:+.2f}, conf={confidence:.2f})"
           f"{aviso_conflito}. Fatores: {detalhe}.")
    logger.info(msg)
    return bias, round(confidence, 4), msg


# ----------------------------------------------------------------------------
# Helpers de justificativa (texto em português)
# ----------------------------------------------------------------------------
def _descreve_contribuicoes(contribs: list[tuple[str, float, float]]) -> str:
    """Monta um texto legível das contribuições por tema (maior primeiro)."""
    partes = []
    for theme, contrib, _coef in sorted(contribs, key=lambda x: -abs(x[1])):
        sinal = "empurra ALTA" if contrib > 0 else "empurra BAIXA"
        partes.append(f"{theme} {sinal} ({contrib:+.2f})")
    return "; ".join(partes)


def _descreve_conflito(contribs: list[tuple[str, float, float]]) -> str:
    """Texto focado em explicitar os dois lados do conflito."""
    altas = [f"{t} ({c:+.2f})" for t, c, _ in contribs if c > 0]
    baixas = [f"{t} ({c:+.2f})" for t, c, _ in contribs if c < 0]
    return (f"forcas de ALTA: {', '.join(altas) or 'nenhuma'} x "
            f"forcas de BAIXA: {', '.join(baixas) or 'nenhuma'}")
