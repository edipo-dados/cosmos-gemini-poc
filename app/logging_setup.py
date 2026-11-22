"""Logging com redação de segredos (chave Gemini e senhas de banco)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import Settings, get_settings

_GEMINI_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
REDACTED = "***"


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self._secrets = sorted({s for s in (secrets or []) if s}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return _GEMINI_KEY.sub(REDACTED, text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        return True


def configure_logging(name: str, settings: Settings | None = None, filename: str | None = None) -> logging.Logger:
    """Logger com saída no console e (opcional) em arquivo dentro de LOG_DIR."""
    settings = settings or get_settings()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if filename:
        log_dir = Path(settings.log_path)
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / filename, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactingFilter(settings.secret_values()))
        logger.addHandler(h)
    logger.propagate = False
    return logger
