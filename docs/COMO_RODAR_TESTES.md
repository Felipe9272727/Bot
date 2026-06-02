# Como rodar os testes

Guia rapido e pratico para rodar os testes do SmartTrader em qualquer sistema
operacional (Linux, macOS ou Windows).

> Os testes de **estrategia**, **risco** e **noticias** rodam em **QUALQUER SO**.
> Eles **nao precisam do MetaTrader5** (que e Windows-only). Voce so precisa do
> MT5 para operar de verdade (live).

## 1. Criar o ambiente virtual

Com o Makefile (recomendado):

```bash
make venv
```

Ou manualmente:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows (PowerShell/CMD)
```

## 2. Instalar as dependencias de teste

O `make venv` ja instala tudo. Se preferir manual:

```bash
pip install --upgrade pip
pip install pandas numpy pytest python-dotenv
```

Nao instale o `MetaTrader5` para rodar os testes — ele e Windows-only e nao e
necessario para estrategia, risco, noticias nem backtest.

## 3. Rodar os testes

```bash
make test
```

Ou direto:

```bash
pytest -q
```

Os testes ficam em `tests/` (`test_strategy.py`, `test_risk.py`,
`test_news_ai.py`).

## 4. Rodar o backtest de exemplo

```bash
make backtest
```

Ou direto:

```bash
python -m smarttrader.backtest
```

## CI automatico no GitHub

A cada `push` e `pull request`, o GitHub Actions roda os testes
automaticamente em **Python 3.11 e 3.12** no Ubuntu. A configuracao esta em
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). O CI nao instala o
MetaTrader5 (Windows-only), entao valida exatamente a parte que roda em
qualquer SO.
