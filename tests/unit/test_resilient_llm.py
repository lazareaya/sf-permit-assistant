"""Free-tier resilience: model fallback chain and per-call timeout."""

import asyncio

import pytest
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from app import resilient_llm
from app.resilient_llm import AllModelsUnavailableError, fallback_chain, make_model


def _fake_parent(behaviour: dict, calls: list):
    """Replace Gemini.generate_content_async: behaviour[model] = 'ok' | code | 'hang'."""

    async def fake(self, llm_request, stream=False):
        model = llm_request.model
        calls.append(model)
        b = behaviour.get(model, "ok")
        if b == "hang":
            await asyncio.sleep(10)
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


def test_times_out_a_hanging_model(monkeypatch):
    monkeypatch.setattr(resilient_llm, "_preferred", {})
    monkeypatch.setenv("AGENT_FALLBACK_MODELS", "m2")
    monkeypatch.setattr(resilient_llm, "PER_CALL_TIMEOUT_S", 0.2)
    calls: list = []
    monkeypatch.setattr(
        Gemini, "generate_content_async", _fake_parent({"m1": "hang"}, calls)
    )
    out = _run(make_model("m1"), LlmRequest(model="m1"))
    assert out[0].content.parts[0].text == "answer from m2"


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
    monkeypatch.setattr(resilient_llm, "TOTAL_BUDGET_S", 4)
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
