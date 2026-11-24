"""Gemini model that survives free-tier saturation: always end with an answer.

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
``AGENT_FALLBACK_MODELS``.

When every model is saturated, the call does **not** give up quickly: it keeps
cycling through the models, with growing pauses (up to 20 s), for up to
``LLM_TOTAL_BUDGET_S`` (14 min). To spare the small daily free quotas of the
fallback models (20 requests/day), every other pass only tries the "lite"
models, and a model whose daily quota is used up is skipped until the quota
resets. A call stuck for more than ``LLM_CALL_MAX_S`` is restarted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
# Seconds after which the whole model call gives up (keep it long: an answer
# late is better than no answer). Cloud Run's request timeout is 30 min.
TOTAL_BUDGET_S = float(os.getenv("LLM_TOTAL_BUDGET_S", "840"))
# Seconds after which a call that is still running is cancelled and retried.
CALL_MAX_S = float(os.getenv("LLM_CALL_MAX_S", "90"))
# Longest pause between two passes when every model failed fast.
MAX_PAUSE_S = 20.0
# The model that answered is tried first for this many seconds.
STICKY_S = float(os.getenv("LLM_STICKY_S", "300"))

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}

_preferred: dict[str, tuple[str, float]] = {}  # primary -> (model, valid until)
_exhausted: dict[str, float] = {}  # model -> daily quota used up until (epoch s)


class AllModelsUnavailableError(RuntimeError):
    """Every model of the chain was saturated or too slow."""


def _next_quota_reset() -> float:
    """Free-tier daily quotas reset at midnight Pacific time (9 h in Paris)."""
    tz = ZoneInfo("America/Los_Angeles")
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=tz).timestamp()


def fallback_chain(primary: str, lite_only: bool = False) -> list[str]:
    extra = os.getenv("AGENT_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    chain = [primary] + [m.strip() for m in extra.split(",") if m.strip()]
    pref = _preferred.get(primary)
    if pref and pref[1] > time.monotonic():
        chain.insert(0, pref[0])  # the model that answered last goes first
    now = time.time()
    chain = [m for m in chain if _exhausted.get(m, 0) <= now]
    if lite_only:
        chain = [m for m in chain if "lite" in m] or chain
    return list(dict.fromkeys(chain))  # dedupe, keep order


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return True
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_CODES
    return False


def reason_daily_quota() -> str:
    return "quota gratuit du jour épuisé (remis à zéro à 9 h, heure de Paris)"


def reason(exc: BaseException | None) -> str:
    """Human-readable (French) reason why a model did not answer."""
    if exc is None or isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return "pas de réponse dans le délai"
    code = getattr(exc, "code", None)
    if code == 429:
        if "PerDay" in str(exc):
            return reason_daily_quota()
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
        running: dict[asyncio.Task, tuple[str, float]] = {}  # task -> (model, start)
        last_exc: BaseException | None = None
        failures: dict[str, str] = {}  # model -> last reason
        passes = 1  # the first queue is pass 1 (all models)

        def launch() -> None:
            model = queue.pop(0)
            req = _request_for(llm_request, model)
            task = asyncio.create_task(self._collect(req, stream))
            running[task] = (model, time.monotonic())

        try:
            while True:
                if not running and not queue:
                    if deadline - time.monotonic() < 2:
                        break
                    # Every model failed fast: pause, then a new pass.
                    await asyncio.sleep(min(3.0 * passes, MAX_PAUSE_S))
                    passes += 1
                    # Odd passes: lite models only, to spare the daily quotas.
                    queue = fallback_chain(primary, lite_only=passes % 2 == 0)
                    if not queue:  # every daily quota is used up: no hope today
                        break
                if queue and (not running or len(running) < MAX_PARALLEL):
                    launch()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = await asyncio.wait(
                    running,
                    timeout=min(HEDGE_DELAY_S, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    model, _start = running.pop(task)
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
                    if getattr(exc, "code", None) == 429 and "PerDay" in str(exc):
                        _exhausted[model] = _next_quota_reset()
                    logger.warning("Model %s unavailable (%s)", model, failures[model])
                # A call stuck for too long is cancelled (its slot is freed).
                for task, (model, start) in list(running.items()):
                    if time.monotonic() - start > CALL_MAX_S:
                        task.cancel()
                        del running[task]
                        failures[model] = f"pas de réponse en {CALL_MAX_S:.0f} s"
                if not done and queue and len(running) < MAX_PARALLEL:
                    logger.info("No answer after %.0f s, hedging", HEDGE_DELAY_S)
        finally:
            for model, _start in running.values():
                failures.setdefault(model, reason(None))
            for task in running:
                task.cancel()
        for model, until in _exhausted.items():
            if until > time.time():
                failures[model] = reason_daily_quota()
        details = " ; ".join(f"{m} : {r}" for m, r in failures.items())
        waited = TOTAL_BUDGET_S - max(0.0, deadline - time.monotonic())
        raise AllModelsUnavailableError(
            f"Aucun modèle Gemini gratuit n'a répondu après {waited / 60:.0f} min "
            f"d'essais. Détail : {details}."
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
