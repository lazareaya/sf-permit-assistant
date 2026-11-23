"""Gemini model that survives free-tier saturation.

On the free tier of Google AI Studio, a model can be overloaded (503 "high
demand"), rate limited (429) or simply hang. Instead of retrying the same
model for minutes, ``ResilientGemini`` gives each model a short time budget and
moves on to the next free model of the chain:

    gemini-3.5-flash-lite -> gemini-3-flash-preview -> gemini-3.5-flash -> ...

The chain is configurable with ``AGENT_FALLBACK_MODELS`` (comma separated).
The whole request is capped (``LLM_TOTAL_BUDGET_S``): past it, the error is
raised and the UI shows a clear "Gemini is saturated" message.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator

from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

logger = logging.getLogger(__name__)

DEFAULT_FALLBACKS = (
    "gemini-3-flash-preview,gemini-3.5-flash,gemini-3.6-flash,gemini-3.1-flash-lite"
)
# Seconds given to one model call before trying the next model.
PER_CALL_TIMEOUT_S = float(os.getenv("LLM_CALL_TIMEOUT_S", "25"))
# Seconds after which the whole model call gives up (all models tried).
TOTAL_BUDGET_S = float(os.getenv("LLM_TOTAL_BUDGET_S", "75"))

# Once the primary model failed, the model that answered is tried first for
# this many seconds, so each call does not wait for the saturated model again.
STICKY_S = float(os.getenv("LLM_STICKY_S", "300"))

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}

_preferred: dict[str, tuple[str, float]] = {}  # primary -> (model, valid until)


class AllModelsUnavailableError(RuntimeError):
    """Every model of the chain was saturated or timed out."""


def fallback_chain(primary: str) -> list[str]:
    extra = os.getenv("AGENT_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    chain = [primary] + [m.strip() for m in extra.split(",") if m.strip()]
    pref = _preferred.get(primary)
    if pref and pref[1] > time.monotonic():
        chain.insert(0, pref[0])  # recently working fallback first
    return list(dict.fromkeys(chain))  # dedupe, keep order


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return True
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_CODES
    return False


class ResilientGemini(Gemini):
    """Gemini with per-call timeout and automatic fallback to other free models."""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        primary = self.model
        chain = fallback_chain(primary)
        deadline = time.monotonic() + TOTAL_BUDGET_S
        last_exc: BaseException | None = None
        for rnd in range(2):  # two passes over the chain, within the budget
            for model in chain:
                remaining = deadline - time.monotonic()
                if remaining <= 1:
                    break
                llm_request.model = model
                try:
                    # Buffer the (non-streamed) responses: nothing is yielded
                    # unless the call fully succeeds, so a fallback never mixes
                    # partial answers of two models.
                    responses = await asyncio.wait_for(
                        self._collect(llm_request, stream),
                        timeout=min(PER_CALL_TIMEOUT_S, remaining),
                    )
                except Exception as exc:
                    if not _retryable(exc):
                        raise
                    last_exc = exc
                    logger.warning(
                        "Model %s unavailable (%s), trying the next one",
                        model,
                        getattr(exc, "code", type(exc).__name__),
                    )
                    continue
                if model != primary:
                    logger.info("Answered by fallback model %s", model)
                    _preferred[primary] = (model, time.monotonic() + STICKY_S)
                else:
                    _preferred.pop(primary, None)
                for resp in responses:
                    yield resp
                return
            if rnd == 0 and deadline - time.monotonic() > 5:
                await asyncio.sleep(3)
        raise AllModelsUnavailableError(
            "Gemini (offre gratuite) est saturé sur tous les modèles essayés. "
            "Réessayez dans un instant."
        ) from last_exc

    async def _collect(
        self, llm_request: LlmRequest, stream: bool
    ) -> list[LlmResponse]:
        return [r async for r in super().generate_content_async(llm_request, stream)]


def make_model(model: str) -> ResilientGemini:
    # One quick retry per model; the fallback chain does the rest.
    return ResilientGemini(
        model=model,
        retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, max_delay=3),
    )
