"""
Servidor HTTP local do serviço de IA do bot de trading (MT4).

Expõe dois endpoints (ver docs/ARQUITETURA.md, "Contrato do serviço de IA"):

    POST /signal   -> recebe features de mercado, devolve decisão da IA.
    GET  /health   -> verificação de saúde do serviço.

O servidor delega a inferência para `predict()` em model.py. Ele é
defensivo: entradas inválidas viram HTTP 400 com mensagem clara, e erros
internos viram HTTP 500 — em nenhum caso o processo derruba.

Configuração por variáveis de ambiente:
    AI_HOST  (padrão 127.0.0.1)
    AI_PORT  (padrão 5000)

Executar:
    python server.py
"""

import logging
import os

from flask import Flask, jsonify, request

# Import relativo robusto: funciona tanto como pacote (ai.model) quanto
# rodando o arquivo diretamente de dentro de ai/.
try:
    from . import model as model_module
except ImportError:  # pragma: no cover - execução direta sem pacote
    import model as model_module


# --------------------------------------------------------------------------- #
# Logging                                                                      #
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ai.server")


# --------------------------------------------------------------------------- #
# App                                                                          #
# --------------------------------------------------------------------------- #
app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Verificação de saúde simples."""
    return jsonify({"status": "ok"}), 200


@app.route("/signal", methods=["POST"])
def signal():
    """
    Recebe JSON {symbol, timeframe, features:{...}} e responde
    {"signal": <1|-1|0>, "confidence": <0..1>}.
    """
    # 1) Corpo precisa ser JSON válido.
    data = request.get_json(silent=True)
    if data is None:
        logger.warning("Requisição /signal sem JSON válido no corpo.")
        return jsonify({"error": "Corpo da requisição deve ser JSON válido."}), 400

    # 2) Campo 'features' obrigatório.
    features = data.get("features")
    if features is None:
        logger.warning("Requisição /signal sem campo 'features'.")
        return jsonify({"error": "Campo 'features' é obrigatório."}), 400

    symbol = data.get("symbol", "?")
    timeframe = data.get("timeframe", "?")

    # 3) Inferência (validação fina das features acontece em model.predict).
    try:
        result = model_module.predict(features)
    except ValueError as exc:
        # Entrada inválida -> 400 com mensagem clara.
        logger.warning("Entrada inválida para %s: %s", symbol, exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - rede de segurança
        # Qualquer erro inesperado -> 500, mas o servidor segue de pé.
        logger.exception("Erro interno ao prever para %s: %s", symbol, exc)
        return jsonify({"error": "Erro interno no serviço de IA."}), 500

    logger.info(
        "signal symbol=%s tf=%s -> signal=%s confidence=%.3f",
        symbol, timeframe, result["signal"], result["confidence"],
    )
    return jsonify(result), 200


def _get_config():
    """Lê host/porta das variáveis de ambiente, com padrões seguros."""
    host = os.environ.get("AI_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("AI_PORT", "5000"))
    except ValueError:
        logger.warning("AI_PORT inválida; usando 5000.")
        port = 5000
    return host, port


if __name__ == "__main__":
    host, port = _get_config()
    logger.info("Iniciando serviço de IA em http://%s:%d", host, port)
    # debug=False para não expor reloader/PIN em ambiente local de trading.
    app.run(host=host, port=port, debug=False)
