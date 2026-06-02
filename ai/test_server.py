"""
Testes do serviço de IA.

Foco principal: validar o CONTRATO de saída de `predict()`:
    - signal pertence a {-1, 0, 1}
    - confidence é float em [0.0, 1.0]
e validar a lógica da regra stub (compra/venda/neutro).

Roda com pytest:
    pytest ai/test_server.py
ou como script autônomo (sem pytest instalado):
    python ai/test_server.py
"""

import os
import sys

# Garante que o diretório do arquivo está no path para importar model.py
# tanto via pytest quanto como script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import model  # noqa: E402


# --------------------------------------------------------------------------- #
# Features de exemplo                                                          #
# --------------------------------------------------------------------------- #
FEATURES_ALTA = {
    "rsi": 45.0, "ema_fast": 1.0850, "ema_slow": 1.0830,
    "price": 1.0845, "spread": 0.8,
}
FEATURES_BAIXA = {
    "rsi": 55.0, "ema_fast": 1.0820, "ema_slow": 1.0840,
    "price": 1.0825, "spread": 0.8,
}
FEATURES_NEUTRO_SOBRECOMPRADO = {
    "rsi": 80.0, "ema_fast": 1.0850, "ema_slow": 1.0830,
    "price": 1.0845, "spread": 0.8,
}
FEATURES_NEUTRO_SOBREVENDIDO = {
    "rsi": 20.0, "ema_fast": 1.0820, "ema_slow": 1.0840,
    "price": 1.0825, "spread": 0.8,
}


def _assert_contract(result):
    """Valida o formato de saída conforme o contrato da arquitetura."""
    assert isinstance(result, dict), "saída deve ser dict"
    assert set(result.keys()) == {"signal", "confidence"}, \
        "saída deve ter exatamente 'signal' e 'confidence'"
    assert result["signal"] in (-1, 0, 1), \
        f"signal inválido: {result['signal']}"
    assert isinstance(result["signal"], int), "signal deve ser int"
    conf = result["confidence"]
    assert isinstance(conf, float), "confidence deve ser float"
    assert 0.0 <= conf <= 1.0, f"confidence fora de [0,1]: {conf}"


# --------------------------------------------------------------------------- #
# Testes de contrato                                                          #
# --------------------------------------------------------------------------- #
def test_contrato_saida_para_varios_inputs():
    for f in (FEATURES_ALTA, FEATURES_BAIXA,
              FEATURES_NEUTRO_SOBRECOMPRADO, FEATURES_NEUTRO_SOBREVENDIDO):
        _assert_contract(model.predict(f))


def test_sinal_compra():
    r = model.predict(FEATURES_ALTA)
    assert r["signal"] == 1
    assert r["confidence"] > 0.0


def test_sinal_venda():
    r = model.predict(FEATURES_BAIXA)
    assert r["signal"] == -1
    assert r["confidence"] > 0.0


def test_sinal_neutro_sobrecomprado():
    r = model.predict(FEATURES_NEUTRO_SOBRECOMPRADO)
    assert r["signal"] == 0
    assert r["confidence"] == 0.0


def test_sinal_neutro_sobrevendido():
    r = model.predict(FEATURES_NEUTRO_SOBREVENDIDO)
    assert r["signal"] == 0


def test_features_faltando_levanta_value_error():
    incompleto = {"rsi": 50.0, "ema_fast": 1.0}
    try:
        model.predict(incompleto)
    except ValueError:
        return
    raise AssertionError("predict deveria levantar ValueError com features faltando")


def test_clamp_confidence():
    assert model._clamp01(-1.0) == 0.0
    assert model._clamp01(2.0) == 1.0
    assert model._clamp01(0.5) == 0.5


# --------------------------------------------------------------------------- #
# Execução como script autônomo                                              #
# --------------------------------------------------------------------------- #
def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} testes passaram.")


if __name__ == "__main__":
    _run_all()
