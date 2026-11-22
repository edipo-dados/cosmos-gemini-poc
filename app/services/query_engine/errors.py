"""Erros do Query Engine. O código é estável e vai para o chamador (ver tabela de códigos em docs/ARCHITECTURE.md, seção 6.1)."""
from __future__ import annotations


class QueryEngineError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}}
