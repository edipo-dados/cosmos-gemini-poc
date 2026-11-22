"""Erros de ferramenta com código estável (docs/ARCHITECTURE.md, seção 6.1)."""
from __future__ import annotations


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}}


class SemanticCatalogUnavailable(ToolError):
    def __init__(self, message: str):
        super().__init__("semantic_catalog_unavailable", message)
