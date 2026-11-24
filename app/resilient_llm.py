"""Gemini model that survives free-tier saturation, without long waits.

On the free tier of Google AI Studio, a model can be overloaded (503 "high
demand"), rate limited (429) or simply hang, and which model is saturated
changes over the day. ``ResilientGemini`` therefore *hedges* its calls:

* the call starts on the first model of the chain;
* if it has not answered after ``LLM_HEDGE_DELAY_S`` (4 s), the next free model
  is started **in parallel** (the first one keeps running: a long but healthy
  answer is never cut);
* a model that fails (503/429...) immediately hands over to the next one;
* the first complete answer wins, the other calls are cancelled.

The model that won is tried first on the next calls (``LLM_STICKY_S``), so a
saturated model does not slow every call down. The chain is configurable with
``AGENT_FALLBACK_MODELS``; past ``LLM_TOTAL_BUDGET_S`` the call gives up and
the UI shows a clear "Gemini is saturated" message.
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
# Seconds without an answer before the next model is started in parallel.
HEDGE_DELAY_S = float(os.getenv("LLM_HEDGE_DELAY_S", "4"))
# Maximum number of models running at the same time for one call.
MAX_PARALLEL = int(os.getenv("LLM_MAX_PARALLEL", "3"))
# Seconds after which the whole model call gives up.
TOTAL_BUDGET_S = float(os.getenv("LLM_TOTAL_BUDGET_S", "60"))
# The model that answered is tried first for this many seconds.
STICKY_S = float(os.getenv("LLM_STICKY_S", "300"))

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}

_preferred: dict[str, tuple[str, float]] = {}  # primary -> (model, valid until)


class AllModelsUnavailableError(RuntimeError):
    """Every model of the chain was saturated or too slow."""


def fallback_chain(primary: str) -> list[str]:
    extra = os.getenv("AGENT_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    chain = [primary] + [m.strip() for m in extra.split(",") if m.strip()]
    pref = _preferred.get(primary)
    if pref and pref[1] > time.monotonic():
        chain.insert(0, pref[0])  # the model that answered last goes first
    return list(dict.fromkeys(chain))  # dedupe, keep order


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return True
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_CODES
    return False


def reason(exc: BaseException | None) -> str:
    """Human-readable (French) reason why a model did not answer."""
    if exc is None or isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return "pas de réponse dans le délai"
    code = getattr(exc, "code", None)
    if code == 429:
        if "PerDay" in str(exc):
            return "quota gratuit du jour épuisé (remis à zéro à 9 h, heure de Paris)"
        return "limite de requêtes par minute atteinte"
    if code in (500, 502, 503, 504):
        return f"serveurs Google surchargés ({code})"
    return f"erreur {code or type(exc).__name__}"


def _request_for(llm_request: LlmRequest, model: str) -> LlmRequest:
    """Independent copy for one model (the parent call mutates its request)."""
    return llm_request.model_copy(
        update={
            "model": model,
            "contents": list(llm_request.contents),
            "config": llm_request.config.model_copy(deep=True),
        }
    )


class ResilientGemini(Gemini):
    """Gemini with hedged calls across several free models."""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        primary = self.model
        queue = fallback_chain(primary)
        deadline = time.monotonic() + TOTAL_BUDGET_S
        running: dict[asyncio.Task, str] = {}
        last_exc: BaseException | None = None
        failures: dict[str, str] = {}  # model -> last reason
        passes = 0

        def launch() -> None:
            model = queue.pop(0)
            req = _request_for(llm_request, model)
            running[asyncio.create_task(self._collect(req, stream))] = model

        try:
            launch()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = await asyncio.wait(
                    running,
                    timeout=min(HEDGE_DELAY_S, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    model = running.pop(task)
                    exc = task.exception()
                    if exc is None:
                        self._remember(primary, model)
                        for resp in task.result():
                            yield resp
                        return
                    if not _retryable(exc):
                        raise exc
                    last_exc = exc
                    failures[model] = reason(exc)
                    logger.warning(
                        "Model %s unavailable (%s)",
                        model,
                        getattr(exc, "code", type(exc).__name__),
                    )
                # No answer yet (slow) or a model failed: start the next one.
                if queue and len(running) < MAX_PARALLEL:
                    if not done:
                        logger.info("No answer after %.0f s, hedging", HEDGE_DELAY_S)
                    launch()
                elif not running:
                    if deadline - time.monotonic() < 4:
                        break
                    # Every model failed fast (503 burst): new pass after a pause.
                    passes += 1
                    await asyncio.sleep(min(2.0 * passes, 6.0))
                    queue = fallback_chain(primary)
                    launch()
        finally:
            for model in running.values():
                failures.setdefault(model, reason(None))
            for task in running:
                task.cancel()
        details = " ; ".join(f"{m} : {r}" for m, r in failures.items())
        raise AllModelsUnavailableError(
            f"Aucun modèle Gemini gratuit n'a répondu en {TOTAL_BUDGET_S:.0f} s. "
            f"Détail : {details}."
        ) from last_exc

    @staticmethod
    def _remember(primary: str, model: str) -> None:
        if model == primary:
            _preferred.pop(primary, None)
        else:
            logger.info("Answered by %s", model)
            _preferred[primary] = (model, time.monotonic() + STICKY_S)

    async def _collect(
        self, llm_request: LlmRequest, stream: bool
    ) -> list[LlmResponse]:
        # Buffered: a call that fails half-way never yields a partial answer.
        return [r async for r in super().generate_content_async(llm_request, stream)]


def make_model(model: str) -> ResilientGemini:
    # No retry on the same model: the hedged chain does it faster.
    return ResilientGemini(
        model=model, retry_options=types.HttpRetryOptions(attempts=1)
    )
