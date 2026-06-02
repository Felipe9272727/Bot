"""
Módulo de modelo (o "cérebro") do serviço de IA.

CONTRATO (definido em docs/ARQUITETURA.md):

    Entrada  -> features: dict com as chaves:
        - rsi       (float)  Índice de Força Relativa, 0..100
        - ema_fast  (float)  Média móvel exponencial rápida (preço)
        - ema_slow  (float)  Média móvel exponencial lenta (preço)
        - price     (float)  Preço atual
        - spread    (float)  Spread atual (informativo; não usado no stub)

    Saída    -> dict no formato:
        {"signal": int, "confidence": float}
        - signal:     1 (COMPRAR) | -1 (VENDER) | 0 (NEUTRO)
        - confidence: float em [0.0, 1.0]

A função pública é `predict(features)`. Por baixo dela existe um modelo
PLUGÁVEL: se um modelo real for carregado em `_MODEL` (via `load_model()`),
ele é usado; caso contrário caímos numa REGRA STUB simples e determinística,
para que o sistema seja testável desde o dia 1.

================================================================
COMO PLUGAR UM MODELO REAL
================================================================
1. Treine seu modelo (sklearn, keras, xgboost, etc.) e salve em
   ai/models/  (ex.: ai/models/model.pkl ou ai/models/model.h5).
2. Implemente o carregamento dentro de `load_model()` abaixo
   (há um exemplo comentado para sklearn/joblib e para keras).
3. Faça `load_model()` devolver um objeto com um método de inferência.
   Adapte `_predict_with_model()` para extrair signal/confidence dele.
4. Nada mais muda: `server.py` continua chamando apenas `predict()`.
================================================================
"""

from typing import Optional

# Chaves obrigatórias que o serviço espera em `features`.
REQUIRED_FEATURES = ("rsi", "ema_fast", "ema_slow", "price", "spread")

# Modelo real carregado em memória. Enquanto for None, usamos a regra stub.
_MODEL: Optional[object] = None


# --------------------------------------------------------------------------- #
# Ponto de extensão: carregamento do modelo real                              #
# --------------------------------------------------------------------------- #
def load_model() -> Optional[object]:
    """
    Carrega o modelo de IA treinado, se existir, e o guarda em `_MODEL`.

    Retorna o objeto do modelo (ou None se nenhum modelo real estiver
    disponível, caso em que o serviço opera com a regra stub).

    >>> ESTE É O LUGAR ONDE VOCÊ PLUGA O MODELO REAL <<<

    Exemplo (sklearn / joblib):
        import os, joblib
        path = os.path.join(os.path.dirname(__file__), "models", "model.pkl")
        if os.path.exists(path):
            return joblib.load(path)
        return None

    Exemplo (keras / tensorflow):
        import os
        from tensorflow import keras
        path = os.path.join(os.path.dirname(__file__), "models", "model.h5")
        if os.path.exists(path):
            return keras.models.load_model(path)
        return None
    """
    global _MODEL
    # Por padrão, nenhum modelo real: ficamos no stub.
    # Descomente/implemente um dos exemplos acima para ativar o modelo real.
    _MODEL = None
    return _MODEL


def _predict_with_model(model: object, features: dict) -> dict:
    """
    Roda a inferência usando um modelo real carregado.

    ADAPTE este corpo ao formato do seu modelo. O esqueleto abaixo monta o
    vetor de features na ordem de REQUIRED_FEATURES e espera que o modelo
    exponha `predict` (e opcionalmente `predict_proba`).

    Deve retornar {"signal": int, "confidence": float}.
    """
    # Vetor de features na ordem canônica.
    x = [[float(features[k]) for k in REQUIRED_FEATURES]]

    # Exemplo genérico (sklearn-like). Ajuste o mapeamento classe->sinal.
    raw = model.predict(x)[0]
    signal = int(raw)
    if signal not in (-1, 0, 1):
        # Mapeie classes do seu modelo para a convenção -1/0/1 aqui.
        signal = 0

    confidence = 1.0
    proba = getattr(model, "predict_proba", None)
    if callable(proba):
        try:
            confidence = float(max(proba(x)[0]))
        except Exception:
            confidence = 1.0

    return {"signal": signal, "confidence": _clamp01(confidence)}


# --------------------------------------------------------------------------- #
# Regra STUB (funciona desde o dia 1)                                         #
# --------------------------------------------------------------------------- #
def _predict_stub(features: dict) -> dict:
    """
    Regra simples baseada em cruzamento de EMAs filtrado por RSI.

    Lógica:
        - ema_fast > ema_slow  e  rsi < 70  -> COMPRAR (1)
          (tendência de alta, ainda não sobrecomprado)
        - ema_fast < ema_slow  e  rsi > 30  -> VENDER (-1)
          (tendência de baixa, ainda não sobrevendido)
        - caso contrário                    -> NEUTRO (0)

    Confiança: proporcional à distância relativa entre as EMAs, normalizada
    pelo preço e amplificada por um fator, com clamp em [0, 1]. Quanto mais
    separadas as EMAs, maior a convicção. Sinal NEUTRO tem confiança 0.
    """
    rsi = float(features["rsi"])
    ema_fast = float(features["ema_fast"])
    ema_slow = float(features["ema_slow"])
    price = float(features["price"])

    if ema_fast > ema_slow and rsi < 70:
        signal = 1
    elif ema_fast < ema_slow and rsi > 30:
        signal = -1
    else:
        signal = 0

    if signal == 0:
        return {"signal": 0, "confidence": 0.0}

    # Distância relativa entre EMAs normalizada pelo preço.
    # Evita divisão por zero usando um piso pequeno.
    denom = abs(price) if abs(price) > 1e-9 else 1e-9
    rel_distance = abs(ema_fast - ema_slow) / denom

    # Fator de escala: separações de ~0.5% do preço já dão confiança alta.
    # (rel_distance * 200) -> 0.005 vira 1.0 antes do clamp.
    confidence = _clamp01(rel_distance * 200.0)

    return {"signal": int(signal), "confidence": float(confidence)}


# --------------------------------------------------------------------------- #
# Utilidades                                                                   #
# --------------------------------------------------------------------------- #
def _clamp01(value: float) -> float:
    """Restringe um número ao intervalo [0.0, 1.0]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _validate_features(features: dict) -> None:
    """
    Garante que `features` é um dict com todas as chaves obrigatórias e
    valores numéricos. Levanta ValueError com mensagem clara caso contrário.
    """
    if not isinstance(features, dict):
        raise ValueError("'features' deve ser um objeto/dict.")

    missing = [k for k in REQUIRED_FEATURES if k not in features]
    if missing:
        raise ValueError(
            "Campos faltando em 'features': " + ", ".join(missing)
        )

    for k in REQUIRED_FEATURES:
        try:
            float(features[k])
        except (TypeError, ValueError):
            raise ValueError(f"Campo '{k}' deve ser numérico.")


# --------------------------------------------------------------------------- #
# API pública                                                                  #
# --------------------------------------------------------------------------- #
def predict(features: dict) -> dict:
    """
    Ponto de entrada único do modelo de IA.

    Recebe `features` (ver contrato no topo do arquivo) e retorna
    {"signal": int, "confidence": float}.

    Usa o modelo real se `_MODEL` estiver carregado; caso contrário usa a
    regra stub. Valida a entrada antes de inferir.
    """
    _validate_features(features)

    if _MODEL is not None:
        return _predict_with_model(_MODEL, features)

    return _predict_stub(features)


# Tenta carregar um modelo real ao importar o módulo (silenciosamente cai no
# stub se não houver modelo). Não derruba o import em caso de erro.
try:
    load_model()
except Exception:  # pragma: no cover - segurança no import
    _MODEL = None


if __name__ == "__main__":
    # Pequena auto-demonstração executável sem dependências externas.
    exemplos = [
        {"rsi": 45.0, "ema_fast": 1.0850, "ema_slow": 1.0830,
         "price": 1.0845, "spread": 0.8},   # alta -> espera 1
        {"rsi": 55.0, "ema_fast": 1.0820, "ema_slow": 1.0840,
         "price": 1.0825, "spread": 0.8},   # baixa -> espera -1
        {"rsi": 80.0, "ema_fast": 1.0850, "ema_slow": 1.0830,
         "price": 1.0845, "spread": 0.8},   # sobrecomprado -> espera 0
    ]
    for f in exemplos:
        print(f, "->", predict(f))
