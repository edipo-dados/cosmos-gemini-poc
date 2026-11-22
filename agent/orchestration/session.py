"""Histórico de conversa em memória (até 20 turnos por sessão, descartado no reinício da API)."""
from __future__ import annotations

import threading

from google.genai import types

MAX_TURNS = 20
MAX_SESSIONS = 500


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, list[tuple[str, str]]] = {}

    def history(self, session_id: str) -> list[types.Content]:
        with self._lock:
            turns = list(self._data.get(session_id, []))
        out: list[types.Content] = []
        for question, answer in turns:
            out.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))
            out.append(types.Content(role="model", parts=[types.Part.from_text(text=answer)]))
        return out

    def add(self, session_id: str, question: str, answer: str) -> None:
        with self._lock:
            turns = self._data.setdefault(session_id, [])
            turns.append((question, answer))
            del turns[:-MAX_TURNS]
            while len(self._data) > MAX_SESSIONS:
                self._data.pop(next(iter(self._data)))
