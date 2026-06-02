"""Garante que a raiz do repositório esteja no sys.path durante os testes.

Com este arquivo na raiz, `pytest` (inclusive no CI, sem `python -m`) consegue
importar o pacote ``smarttrader`` sem precisar de PYTHONPATH ou instalação.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
