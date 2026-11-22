"""Cliente Gemini com o SDK oficial `google-genai`. Function Calling manual: a chamada automática do SDK fica desligada,
porque cada chamada de ferramenta precisa passar pelo gateway do Cosmos e ser auditada (docs/ARCHITECTURE.md, seção 5.1).
Chave e modelo vêm do ambiente (GEMINI_API_KEY, GEMINI_MODEL). A chave nunca é registrada em log."""
from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from google import genai
from google.genai import types

from .declarations import build_tools
from .errors import GeminiError, GeminiNotConfigured, is_retryable, map_error
from .prompts import SYSTEM_INSTRUCTION

log = logging.getLogger("poc.gemini")
RETRY_DELAYS = (1.0, 2.0)  # até 2 novas tentativas para 429 e 5xx
BLOCK_FINISH = {types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT, types.FinishReason.BLOCKLIST,
                types.FinishReason.SPII, types.FinishReason.RECITATION, types.FinishReason.IMAGE_SAFETY}


class LLMClient(Protocol):
    model: str

    def generate(self, contents: list[types.Content]) -> types.GenerateContentResponse: ...


def build_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0,
        tools=build_tools(),
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.AUTO)),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def is_blocked(response: types.GenerateContentResponse) -> bool:
    if response.prompt_feedback and response.prompt_feedback.block_reason:
        return True
    cands = response.candidates or []
    return bool(cands) and cands[0].finish_reason in BLOCK_FINISH


class GeminiClient:
    def __init__(self, api_key: str, model: str, http_options: types.HttpOptions | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise GeminiNotConfigured("GEMINI_API_KEY não está definida no ambiente. Configure a chave para usar o chat.")
        if not model:
            raise GeminiNotConfigured("GEMINI_MODEL não está definido no ambiente.")
        self.model = model
        self._sleep = sleep
        self._config = build_config()
        self._client = genai.Client(api_key=api_key, http_options=http_options)

    def generate(self, contents: list[types.Content]) -> types.GenerateContentResponse:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self._client.models.generate_content(model=self.model, contents=contents, config=self._config)
            except Exception as exc:  # noqa: BLE001 - tudo é mapeado para um erro estável
                if is_retryable(exc) and attempt < len(RETRY_DELAYS):
                    log.warning("Gemini indisponível (tentativa %d); nova tentativa em %.0f s", attempt + 1, RETRY_DELAYS[attempt])
                    self._sleep(RETRY_DELAYS[attempt])
                    continue
                mapped: GeminiError = map_error(exc)
                (log.error if mapped.http_status == 503 else log.warning)("Gemini: %s", mapped.code)
                raise mapped from None
        raise AssertionError("inalcançável")  # pragma: no cover
