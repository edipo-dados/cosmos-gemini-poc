"""Modelos de entrada da API (`extra="forbid"`: a API é a fronteira de confiança)."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_BODY_BYTES = 16 * 1024
MAX_QUESTION = 2000


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    session_id: str | None = None
