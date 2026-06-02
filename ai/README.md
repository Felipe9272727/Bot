# Serviço de IA (o "cérebro") — `ai/`

Serviço HTTP local em Flask que recebe features de mercado do Expert Advisor
(MT4, via `WebRequest`) e devolve uma decisão de trading. Funciona desde o
dia 1 com uma regra "stub"; o modelo real é plugável em `model.py`.

Contrato completo: ver `docs/ARQUITETURA.md`, seção "Contrato do serviço de IA".

## Estrutura

```
ai/
├── server.py          # servidor Flask (POST /signal, GET /health)
├── model.py           # predict(features) -> {signal, confidence} (stub + plugável)
├── test_server.py     # testes do contrato de saída
├── requirements.txt   # dependências
└── README.md          # este arquivo
```

## 1. Criar venv e instalar dependências

```bash
cd ai
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Rodar o servidor

```bash
python server.py
# Servidor em http://127.0.0.1:5000
```

Host/porta são configuráveis por variável de ambiente:

```bash
AI_HOST=127.0.0.1 AI_PORT=5000 python server.py
```

## 3. Testar com curl

Health check:

```bash
curl http://127.0.0.1:5000/health
# {"status":"ok"}
```

Pedir um sinal (`POST /signal`):

```bash
curl -X POST http://127.0.0.1:5000/signal \
  -H "Content-Type: application/json" \
  -d '{
        "symbol": "EURUSD",
        "timeframe": 15,
        "features": {
          "rsi": 48.2,
          "ema_fast": 1.0832,
          "ema_slow": 1.0840,
          "price": 1.0835,
          "spread": 0.8
        }
      }'
# {"signal": -1, "confidence": 0.147}
```

Se faltar algum campo de `features`, o servidor responde HTTP 400 com uma
mensagem clara — e nunca derruba.

## 4. Rodar os testes

```bash
pytest test_server.py            # se pytest estiver instalado
# ou, sem pytest:
python test_server.py
```

## 5. IMPORTANTE — liberar a URL no MetaTrader 4

Para o EA conseguir chamar este serviço via `WebRequest`, adicione a URL na
lista de permissões do terminal:

> **Ferramentas > Opções > Expert Advisors >**
> marque **"Permitir WebRequest para as URLs listadas"** e adicione:
>
> ```
> http://127.0.0.1:5000
> ```

Sem isso, o `WebRequest` falha (erro 4060/4014) e `GetAISignal` retorna 0.

## 6. Onde plugar o modelo REAL

Todo o ponto de extensão está em **`model.py`**:

- A função **`load_model()`** é onde você carrega seu modelo treinado
  (sklearn/joblib, keras, xgboost, etc.). Há exemplos comentados lá.
  Coloque os arquivos do modelo em `ai/models/` (ex.: `ai/models/model.pkl`).
- A função **`_predict_with_model()`** converte a saída do modelo para o
  formato `{"signal": int, "confidence": float}` — ajuste o mapeamento de
  classes para a convenção `1 / -1 / 0`.
- Enquanto `load_model()` devolver `None`, o serviço usa a **regra stub**
  (cruzamento de EMAs filtrado por RSI). `server.py` nunca muda: ele só
  chama `predict()`.

A troca do stub pelo modelo real é trivial: implemente `load_model()` para
devolver o objeto do modelo e pronto.
