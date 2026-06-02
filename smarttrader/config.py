"""Configuração do SmartTrader.

Carrega credenciais e parâmetros de risco/estratégia a partir do ambiente
ou de um arquivo `.env` (ver `.env.example`). Não quebra se o `.env` não
existir — nesse caso usa variáveis de ambiente já presentes e/ou os defaults
sensatos (idênticos aos do `.env.example`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# python-dotenv é opcional em tempo de import: se não estiver instalado,
# seguimos usando apenas as variáveis de ambiente do processo.
try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:  # pragma: no cover - caminho só quando a lib falta
    _load_dotenv = None


# ---------------------------------------------------------------------------
# Estrutura de configuração
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Todos os campos do `.env.example`, já tipados."""

    # --- Conta MetaTrader 5 ---
    mt5_login: int
    mt5_password: str
    mt5_server: str
    mt5_path: str

    # --- Operação ---
    symbols: list[str] = field(default_factory=lambda: ["EURUSD", "GBPUSD"])
    timeframe: str = "H1"
    htf_timeframe: str = "D1"
    magic: int = 20240602
    dry_run: bool = True
    use_ai: bool = False

    # --- Risco ---
    risk_percent: float = 1.0
    atr_sl_mult: float = 1.8
    tp_r_multiple: float = 1.0
    partial_close_pct: float = 50.0
    breakeven_buffer_atr: float = 0.2
    trailing_atr_mult: float = 2.5
    max_open_trades: int = 1
    max_daily_loss_pct: float = 5.0
    max_drawdown_pct: float = 15.0
    max_consec_losses: int = 4

    # --- Sessão de operação (hora do servidor da corretora) ---
    use_session_filter: bool = True
    session_start_hour: int = 13
    session_end_hour: int = 17

    # --- IA de notícias (opcional) ---
    news_api_key: str = ""
    llm_api_key: str = ""


# ---------------------------------------------------------------------------
# Helpers de parsing (tolerantes a espaços / maiúsculas)
# ---------------------------------------------------------------------------
def _get(env: dict, key: str, default: str) -> str:
    """Lê uma chave do ambiente; remove comentários inline (` # ...`) e espaços.

    No `.env.example` há comentários na mesma linha (ex.: `SYMBOLS=EURUSD # ...`).
    O python-dotenv geralmente já os remove, mas alguns formatos deixam o
    comentário grudado — então limpamos por segurança.
    """
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    # Remove comentário inline somente quando há espaço antes do '#'.
    if " #" in raw:
        raw = raw.split(" #", 1)[0]
    return raw.strip()


def _parse_bool(value: str) -> bool:
    """Converte "true/false" (e variações) em bool."""
    return value.strip().lower() in {"true", "1", "yes", "y", "sim", "on"}


def _parse_int(value: str, key: str) -> int:
    try:
        return int(float(value))  # aceita "1" e "1.0"
    except (ValueError, TypeError):
        raise ValueError(f"Config inválida: {key!r} deve ser inteiro, recebido {value!r}")


def _parse_float(value: str, key: str) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Config inválida: {key!r} deve ser número, recebido {value!r}")


def _parse_list(value: str) -> list[str]:
    """CSV -> lista de strings (sem vazios, sem espaços extras)."""
    return [item.strip() for item in value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Carregamento + validação
# ---------------------------------------------------------------------------
def load_config(env_path: str = ".env") -> Config:
    """Lê o `.env`/ambiente, faz parsing dos tipos e valida o básico.

    Não falha se o `.env` não existir: usa as variáveis de ambiente já
    presentes e os defaults do `.env.example`.
    """
    # Carrega o .env no os.environ se a lib existir e o arquivo existir.
    # `override=False` para não pisar em variáveis já definidas no ambiente.
    if _load_dotenv is not None and env_path and os.path.exists(env_path):
        _load_dotenv(env_path, override=False)

    env = os.environ

    cfg = Config(
        # --- Conta MT5 ---
        mt5_login=_parse_int(_get(env, "MT5_LOGIN", "0"), "MT5_LOGIN"),
        mt5_password=_get(env, "MT5_PASSWORD", ""),
        mt5_server=_get(env, "MT5_SERVER", ""),
        mt5_path=_get(env, "MT5_PATH", ""),
        # --- Operação ---
        symbols=_parse_list(_get(env, "SYMBOLS", "EURUSD,GBPUSD")),
        timeframe=_get(env, "TIMEFRAME", "H1"),
        htf_timeframe=_get(env, "HTF_TIMEFRAME", "D1"),
        magic=_parse_int(_get(env, "MAGIC", "20240602"), "MAGIC"),
        dry_run=_parse_bool(_get(env, "DRY_RUN", "true")),
        use_ai=_parse_bool(_get(env, "USE_AI", "false")),
        # --- Risco ---
        risk_percent=_parse_float(_get(env, "RISK_PERCENT", "1.0"), "RISK_PERCENT"),
        atr_sl_mult=_parse_float(_get(env, "ATR_SL_MULT", "1.8"), "ATR_SL_MULT"),
        tp_r_multiple=_parse_float(_get(env, "TP_R_MULTIPLE", "1.0"), "TP_R_MULTIPLE"),
        partial_close_pct=_parse_float(_get(env, "PARTIAL_CLOSE_PCT", "50"), "PARTIAL_CLOSE_PCT"),
        breakeven_buffer_atr=_parse_float(
            _get(env, "BREAKEVEN_BUFFER_ATR", "0.2"), "BREAKEVEN_BUFFER_ATR"
        ),
        trailing_atr_mult=_parse_float(
            _get(env, "TRAILING_ATR_MULT", "2.5"), "TRAILING_ATR_MULT"
        ),
        max_open_trades=_parse_int(_get(env, "MAX_OPEN_TRADES", "1"), "MAX_OPEN_TRADES"),
        max_daily_loss_pct=_parse_float(
            _get(env, "MAX_DAILY_LOSS_PCT", "5.0"), "MAX_DAILY_LOSS_PCT"
        ),
        max_drawdown_pct=_parse_float(
            _get(env, "MAX_DRAWDOWN_PCT", "15.0"), "MAX_DRAWDOWN_PCT"
        ),
        max_consec_losses=_parse_int(
            _get(env, "MAX_CONSEC_LOSSES", "4"), "MAX_CONSEC_LOSSES"
        ),
        # --- Sessão ---
        use_session_filter=_parse_bool(_get(env, "USE_SESSION_FILTER", "true")),
        session_start_hour=_parse_int(_get(env, "SESSION_START_HOUR", "13"), "SESSION_START_HOUR"),
        session_end_hour=_parse_int(_get(env, "SESSION_END_HOUR", "17"), "SESSION_END_HOUR"),
        # --- IA ---
        news_api_key=_get(env, "NEWS_API_KEY", ""),
        llm_api_key=_get(env, "LLM_API_KEY", ""),
    )

    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    """Validações básicas com mensagens claras (em português)."""
    erros: list[str] = []

    # Risco por trade tem que ser positivo (e abaixo de 100%, óbvio).
    if cfg.risk_percent <= 0:
        erros.append("RISK_PERCENT deve ser > 0.")
    if cfg.risk_percent > 100:
        erros.append("RISK_PERCENT não pode ser > 100.")

    # Travas de risco precisam ser positivas para fazer sentido.
    if cfg.max_daily_loss_pct <= 0:
        erros.append("MAX_DAILY_LOSS_PCT deve ser > 0.")
    if cfg.max_drawdown_pct <= 0:
        erros.append("MAX_DRAWDOWN_PCT deve ser > 0.")
    if cfg.max_consec_losses <= 0:
        erros.append("MAX_CONSEC_LOSSES deve ser > 0.")
    if cfg.max_open_trades <= 0:
        erros.append("MAX_OPEN_TRADES deve ser > 0.")

    # Multiplicadores de ATR têm que ser positivos.
    if cfg.atr_sl_mult <= 0:
        erros.append("ATR_SL_MULT deve ser > 0.")

    # Parcial é uma porcentagem 0..100.
    if not (0 <= cfg.partial_close_pct <= 100):
        erros.append("PARTIAL_CLOSE_PCT deve estar entre 0 e 100.")

    # Horas de sessão no intervalo válido [0, 23].
    if not (0 <= cfg.session_start_hour <= 23):
        erros.append("SESSION_START_HOUR deve estar entre 0 e 23.")
    if not (0 <= cfg.session_end_hour <= 23):
        erros.append("SESSION_END_HOUR deve estar entre 0 e 23.")

    # Precisa de pelo menos um símbolo para operar.
    if not cfg.symbols:
        erros.append("SYMBOLS não pode ser vazio.")

    if erros:
        raise ValueError("Configuração inválida:\n  - " + "\n  - ".join(erros))


__all__ = ["Config", "load_config"]
