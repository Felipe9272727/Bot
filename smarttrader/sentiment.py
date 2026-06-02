"""Sentimento financeiro com FinBERT (opcional, plugável).

Wrapper fino sobre um modelo FinBERT (pré-treinado OU o seu fine-tunado no
Colab). O import de ``transformers``/``torch`` é PROTEGIDO: este módulo importa
em qualquer máquina; só exige as libs quando você realmente usa o scorer.

Uso:
    from smarttrader.sentiment import FinBertSentiment
    fb = FinBertSentiment("/caminho/para/finbert_ft")   # ou "ProsusAI/finbert"
    label, conf = fb.score("Oil prices spike after OPEC cut")
"""
from __future__ import annotations

import logging

log = logging.getLogger("smarttrader.sentiment")

# Import protegido: roda em qualquer máquina; só precisa das libs ao usar.
try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    _HAS_TF = True
except Exception:  # pragma: no cover - depende do ambiente
    _HAS_TF = False


class FinBertSentiment:
    """Carrega um FinBERT e devolve (label, confiança) para um texto.

    model_path: pasta do seu modelo fine-tunado (ex.: 'finbert_ft' baixado do
    Colab) OU um id do HuggingFace (padrão 'ProsusAI/finbert', já treinado).
    """

    def __init__(self, model_path: str = "ProsusAI/finbert"):
        if not _HAS_TF:
            raise RuntimeError(
                "transformers/torch não instalados. Rode: pip install transformers torch"
            )
        self.model_path = model_path
        self.tok = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self.model.eval()

    def score(self, texto: str) -> tuple[str, float]:
        """Retorna (label, confiança 0..1). Label conforme o modelo (ex.:
        positive/negative/neutral)."""
        inp = self.tok(texto, return_tensors="pt", truncation=True, padding=True)
        with torch.no_grad():
            logits = self.model(**inp).logits
        probs = torch.softmax(logits, dim=1)[0]
        i = int(probs.argmax())
        return self.model.config.id2label[i], float(probs[i])

    def avg_confidence(self, textos: list[str]) -> float:
        """Confiança média de sentimento (0..1) de uma lista de textos.

        Útil para *reforçar/atenuar* a confiança do viés direcional: notícias com
        sentimento forte e consistente => confiança maior.
        """
        if not textos:
            return 0.0
        return sum(self.score(t)[1] for t in textos) / len(textos)
