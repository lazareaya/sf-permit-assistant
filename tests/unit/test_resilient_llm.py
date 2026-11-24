"""Free-tier resilience: hedged calls across a chain of free models."""

import asyncio
import time

import pytest
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from app import resilient_llm
from app.resilient_llm import AllModelsUnavailableError, fallback_chain, make_model


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setattr(resilient_llm, "_exhausted", {})
    monkeypatch.setattr(resilient_llm, "MAX_PAUSE_S", 0.3)


def _fake_parent(behaviour: dict, calls: list):
    """Replace Gemini.generate_content_async.

    behaviour[model] = 'ok' | HTTP code | 'hang' | float (seconds before answering).
    """

    async def fake(self, llm_request, stream=False):
        model = llm_request.model
        calls.append(model)
        b = behaviour.get(model, "ok")
        if b == "hang":
            await asyncio.sleep(10)
        if isinstance(b, float):
            await asyncio.sleep(b)
        if isinstance(b, int):
            raise (
                errors.ServerError(b, {"error": {"message": "high demand"}})
                if b >= 500
                else errors.ClientError(b, {"error": {"message": "x"}})
            )
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=f"answer from {model}")]
            )
        )

    return fake


def _run(model, req):
    async def go():
        return [r async for r in model.generate_content_async(req)]

    return asyncio.run(go())


def test_chain_starts_with_primary_and_dedupes(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "b, a ,c")
    assert fallback_chain("a") == ["a", "b", "c"]


def test_falls_back_on_503_and_429(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2,m3")
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": 503, "m2": 429}, calls)
    )
    out = _run(make_model("m1"), LlmRequest(model="m1"))
    assert calls == ["m1", "m2", "m3"]
    assert out[0].content.parts[0].text == "answer from m3"


def test_hanging_model_is_hedged_quickly(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    monkeypatch.setattr(resilient_llm, "HEDGE_DELAY_S", 0.2)
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": "hang"}, calls)
    )
    start = time.monotonic()
    out = _run(make_model("m1"), LlmRequest(model="m1"))
    assert out[0].content.parts[0].text == "answer from m2"
    assert time.monotonic() - start < 2  # not the 10 s of the hanging model


def test_slow_but_healthy_answer_is_not_cut(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    monkeypatch.setattr(resilient_llm, "HEDGE_DELAY_S", 0.2)
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": 0.6, "m2": "hang"}, calls)
    )
    out = _run(make_model("m1"), LlmRequest(model="m1"))
    assert calls == ["m1", "m2"]  # m2 started in parallel...
    assert out[0].content.parts[0].text == "answer from m1"  # ...but m1 kept running


def test_non_retryable_error_is_raised(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": 400}, calls)
    )
    with pytest.raises(errors.ClientError):
        _run(make_model("m1"), LlmRequest(model="m1"))
    assert calls == ["m1"]


def test_all_models_saturated_gives_clear_error(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    monkeypatch.setattr(resilient_llm, "TOTAL_BUDGET_S", 7)
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": 503, "m2": 503}, calls)
    )
    with pytest.raises(AllModelsUnavailableError):
        _run(make_model("m1"), LlmRequest(model="m1"))


def test_working_fallback_is_tried_first_next_time(monkeypatch):
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2,m3")
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": 503, "m2": 503}, calls)
    )
    model = make_model("m1")
    _run(model, LlmRequest(model="m1"))
    calls.clear()
    out = _run(model, LlmRequest(model="m1"))
    assert calls == ["m3"]  # the saturated models are not waited for again
    assert out[0].content.parts[0].text == "answer from m3"


def test_failure_message_gives_the_reason_per_model(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    monkeypatch.setattr(resilient_llm, "TOTAL_BUDGET_S", 3)
    daily = errors.ClientError(
        429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}
    )

    async def fake(self, llm_request, stream=False):
        if llm_request.model == "m1":
            raise errors.ServerError(503, {"error": {"message": "high demand"}})
        raise daily
        yield  # pragma: no cover

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    with pytest.raises(AllModelsUnavailableError) as err:
        _run(make_model("m1"), LlmRequest(model="m1"))
    msg = str(err.value)
    assert "m1 : serveurs Google surchargés (503)" in msg
    assert "m2 : quota gratuit du jour épuisé" in msg


def test_keeps_trying_until_a_model_answers(monkeypatch):
    """A long saturation burst: the call keeps cycling instead of giving up."""
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2-lite,m3")
    calls: list = []
    state = {"n": 0}

    async def fake(self, llm_request, stream=False):
        calls.append(llm_request.model)
        state["n"] += 1
        if state["n"] < 12:  # 11 failures in a row, over several passes
            raise errors.ServerError(503, {"error": {"message": "high demand"}})
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="enfin")])
        )

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    out = _run(make_model("m1-lite"), LlmRequest(model="m1-lite"))
    assert out[0].content.parts[0].text == "enfin"
    # every other pass only tries the lite models (m3 is spared)
    assert calls.count("m3") < calls.count("m1-lite")


def test_daily_quota_model_is_skipped_afterwards(monkeypatch):
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    daily = errors.ClientError(
        429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}
    )
    calls: list = []

    async def fake(self, llm_request, stream=False):
        calls.append(llm_request.model)
        if llm_request.model == "m1":
            raise daily
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="ok")])
        )

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    model = make_model("m1")
    _run(model, LlmRequest(model="m1"))
    calls.clear()
    _run(model, LlmRequest(model="m1"))
    assert calls == ["m2"]  # m1 is not called again before its quota resets


def test_stuck_call_is_restarted(monkeypatch):
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "")
    monkeypatch.setattr(resilient_llm, "CALL_MAX_S", 0.3)
    monkeypatch.setattr(resilient_llm, "HEDGE_DELAY_S", 0.1)
    state = {"n": 0}

    async def fake(self, llm_request, stream=False):
        state["n"] += 1
        if state["n"] == 1:
            await asyncio.sleep(10)  # the first call hangs
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="relancé")])
        )

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    start = time.monotonic()
    out = _run(make_model("m1"), LlmRequest(model="m1"))
    assert out[0].content.parts[0].text == "relancé"
    assert time.monotonic() - start < 3
