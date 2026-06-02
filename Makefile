# Makefile do SmartTrader
#
# Atalhos para tarefas comuns de desenvolvimento.
#
# IMPORTANTE: o pacote MetaTrader5 (usado para operar de verdade) SO funciona
# no Windows. Em Linux/macOS a instalacao dele falha — mas estrategia, risco,
# noticias, testes e backtest rodam normalmente sem o MT5. Os alvos abaixo
# instalam apenas as dependencias de teste (sem MetaTrader5).

# Python e venv
PYTHON ?= python3
VENV   := .venv
VENV_BIN := $(VENV)/bin

.PHONY: help venv test backtest run clean

# Alvo padrao: mostra a ajuda.
help:
	@echo "Alvos disponiveis:"
	@echo "  make venv      - cria o .venv e instala as deps de teste (sem MT5)"
	@echo "  make test      - roda os testes com pytest"
	@echo "  make backtest  - roda o backtest de exemplo"
	@echo "  make run       - roda o trader uma unica vez (--once)"
	@echo "  make clean     - remove .venv, caches e arquivos temporarios"

# Cria o ambiente virtual e instala as dependencias de teste.
# NAO instala MetaTrader5 (Windows-only).
venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install pandas numpy pytest python-dotenv

# Roda a suite de testes.
test:
	$(VENV_BIN)/pytest -q

# Roda o backtest de exemplo.
backtest:
	$(VENV_BIN)/python -m smarttrader.backtest

# Roda o trader uma unica vez (modo --once, sem loop continuo).
run:
	$(VENV_BIN)/python -m smarttrader.trader --once

# Limpa ambiente virtual, caches e arquivos compilados.
clean:
	rm -rf $(VENV)
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
