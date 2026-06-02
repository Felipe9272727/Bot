# 🛠️ Instalação e Teste (MetaTrader 5 + Python)

Guia passo a passo para rodar o SmartTrader. Comece **sempre** com conta DEMO
e `DRY_RUN=true`. Nada de dinheiro real até a demo provar valor.

---

## Parte 1 — Testar a lógica em QUALQUER computador (sem MT5)

Os testes e o backtest **não precisam do MetaTrader 5** (só de Python).

1. Instale Python 3.11+ (https://www.python.org/downloads/).
2. No terminal, dentro da pasta do projeto:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate

   pip install pandas numpy pytest python-dotenv
   pytest -q                       # deve passar todos os testes
   python -m smarttrader.backtest  # mostra um backtest de exemplo
   ```
   (Ou simplesmente `make venv && make test && make backtest`.)

> O backtest de exemplo usa **dados sintéticos** — serve só para ver a engrenagem
> funcionando, **não** é prova de lucro. Para validar de verdade, exporte dados
> históricos reais do MT5 e rode com eles.

---

## Parte 2 — Rodar com o MT5 (conta DEMO)

> O pacote `MetaTrader5` só funciona no **Windows** com o terminal MT5 instalado.

### 2.1 Instalar o MT5 e abrir conta demo
1. Baixe o MetaTrader 5 (https://www.metatrader5.com/) e instale.
2. Abra o terminal → **Arquivo → Abrir uma conta** → escolha um broker →
   selecione **Conta de demonstração** (dinheiro fake). Anote **login**,
   **senha** e **servidor** (ex.: `MetaQuotes-Demo`).
3. No terminal: **Ferramentas → Opções → Expert Advisors** e marque
   **"Permitir trading algorítmico"**. Confirme que o botão **"Algo Trading"**
   na barra está ligado (verde).

### 2.2 Instalar as dependências Python
```bash
pip install -r requirements.txt
```
No Windows isso instala também o pacote `MetaTrader5`. (Em Linux/macOS ele é
ignorado — por isso a Parte 1 roda em qualquer lugar.)

### 2.3 Configurar credenciais
1. Copie `.env.example` para `.env`.
2. Preencha `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` com os dados da **conta demo**.
3. Confira os parâmetros:
   - `DRY_RUN=true` → o bot **mostra a decisão sem enviar ordem** (paper). Comece assim.
   - `USE_AI=false` → opera só com a estratégia técnica (a IA de notícias é opcional/plugável).
   - `SYMBOLS=EURUSD,GBPUSD`, `TIMEFRAME=H1`, `HTF_TIMEFRAME=D1`.
   - Risco conservador para iniciante: `RISK_PERCENT=0.5`, `MAX_DRAWDOWN_PCT=15`.

> 🔒 **Nunca** suba o `.env` para o GitHub (já está no `.gitignore`).

### 2.4 Rodar
```bash
# Um ciclo só, em DRY_RUN: mostra o que ele DECIDIRIA, sem operar
python -m smarttrader.trader --once

# Quando estiver confiante, em conta DEMO, mude DRY_RUN=false no .env
# e rode o laço 24h:
python -m smarttrader.trader
```
- Pare a qualquer momento com **Ctrl+C**.
- Acompanhe os logs: ele informa cada decisão, trava de risco e ordem.

---

## Parte 3 — Plugar a IA de notícias (opcional, depois)

O motor `news_ai.py` hoje é um **stub** (sempre neutro). Para ativar a IA que
decide direção pelas notícias:
1. Implemente `_fetch_news` usando `news_sources.py` (RSS/GDELT/Finnhub).
2. Plugue um modelo de sentimento (FinBERT) em `_score_sentiment`.
3. Plugue um LLM em `_interpret_macro` (ou use `news_mapper.py` como baseline).
4. Coloque as chaves em `.env` (`NEWS_API_KEY`, `LLM_API_KEY`) e ligue `USE_AI=true`.

Detalhes e fontes em [`IA_NOTICIAS.md`](IA_NOTICIAS.md).

---

## ✅ Checklist de segurança antes de pensar em dinheiro real
- [ ] Testes passando (`pytest`)
- [ ] Backtest com **dados reais** (não sintéticos), com custos, fora-de-amostra
- [ ] Pelo menos **3-6 meses** em conta DEMO com o sistema completo
- [ ] Drawdown e expectância dentro do esperado no diário de operações
- [ ] Você entende cada trava de risco do `risk.py`
