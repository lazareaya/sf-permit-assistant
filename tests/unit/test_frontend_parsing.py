from frontend.streamlit_app import parse_events


def test_answer_split_in_several_parts_is_joined():
    events = [
        {
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "name": "search_permits",
                            "args": {"address": "781 20th Ave"},
                        }
                    }
                ]
            }
        },
        {
            "content": {
                "parts": [
                    {
                        "functionResponse": {
                            "name": "search_permits",
                            "response": {"permit_count": 8},
                        }
                    }
                ]
            }
        },
        {
            "content": {
                "parts": [
                    {"text": "Je ne traite que "},
                    {"text": "3 types de demandes."},
                ]
            }
        },
    ]
    text, steps = parse_events(events)
    assert text == "Je ne traite que 3 types de demandes."
    assert [s["type"] for s in steps] == ["call", "result"]


def test_recorded_answer_is_replayed_offline(tmp_path, monkeypatch):
    import frontend.streamlit_app as ui

    monkeypatch.setattr(ui, "REPLAYS_PATH", tmp_path / "replays.json")
    events = [{"content": {"parts": [{"text": "Voici les documents requis."}]}}]
    ui.save_replay("Quels documents pour une rénovation de cuisine ?", events)
    # punctuation, case and accents do not matter
    text, _ = ui.answer("quels documents pour une renovation de cuisine", offline=True)
    assert "Voici les documents requis." in text and "enregistrée" in text
    text, steps = ui.answer("Une question jamais posée", offline=True)
    assert "aucune réponse enregistrée" in text and steps == []


def test_saturated_agent_falls_back_to_recording(tmp_path, monkeypatch):
    import httpx

    import frontend.streamlit_app as ui

    monkeypatch.setattr(ui, "REPLAYS_PATH", tmp_path / "replays.json")

    def timeout(*_a, **_k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(ui, "run_agent", timeout)
    monkeypatch.setattr(ui.st, "session_state", type("S", (), {"session_id": "s"})())
    text, _ = ui.answer("Question sans enregistrement", offline=False)
    assert "saturé" in text
    ui.save_replay("Question enregistrée", [{"content": {"parts": [{"text": "OK"}]}}])
    text, _ = ui.answer("Question enregistrée", offline=False)
    assert text.endswith("OK") and "Pas de réponse de l'agent" in text


def test_progress_labels_for_each_step():
    from frontend.streamlit_app import describe_event

    call = {
        "content": {
            "parts": [
                {
                    "functionCall": {
                        "name": "search_permits",
                        "args": {"address": "781 20th Ave"},
                    }
                }
            ]
        }
    }
    assert "781 20th Ave" in describe_event(call) and "DataSF" in describe_event(call)
    skill = {
        "content": {
            "parts": [
                {
                    "functionCall": {
                        "name": "activate_skill",
                        "args": {"skill_name": "document_requirements"},
                    }
                }
            ]
        }
    }
    assert "documents requis" in describe_event(skill)
    mcp = {
        "content": {
            "parts": [
                {
                    "functionResponse": {
                        "name": "search_permits",
                        "response": {
                            "content": [{"text": '{"permit_count": 8, "permits": []}'}]
                        },
                    }
                }
            ]
        }
    }
    assert "8 permis trouvés" in describe_event(mcp)
    err = {
        "content": {
            "parts": [
                {
                    "functionResponse": {
                        "name": "search_permits",
                        "response": {"error": "DATASF_TIMEOUT", "message": "API lente"},
                    }
                }
            ]
        }
    }
    assert "DATASF_TIMEOUT" in describe_event(err)
    assert (
        describe_event({"content": {"parts": [{"text": "Réponse"}]}})
        == "✍️ Réponse rédigée"
    )


def test_failure_reasons_are_explicit():
    import httpx

    from frontend.streamlit_app import AgentError, explain_failure

    saturated = AgentError(
        "AllModelsUnavailableError: Aucun modèle Gemini gratuit n'a répondu en 60 s. "
        "Détail : gemini-3.5-flash : quota gratuit du jour épuisé."
    )
    assert "quota gratuit du jour épuisé" in explain_failure(saturated)
    req = httpx.Request("POST", "https://agent/run_sse")
    expired = httpx.HTTPStatusError(
        "x", request=req, response=httpx.Response(403, request=req)
    )
    assert "jeton" in explain_failure(expired)
    assert "Pas de réponse" in explain_failure(httpx.ReadTimeout("slow"))
    assert "injoignable" in explain_failure(httpx.ConnectError("refused"))


def _serve(monkeypatch, ui, body: str) -> None:
    """Make ui.run_agent read ``body`` as the /run_sse response."""
    import httpx

    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body))
    )

    def stream(method, url, **kwargs):
        kwargs.pop("timeout", None)
        return client.stream(method, url, **kwargs)

    monkeypatch.setattr(ui.httpx, "stream", stream)


def test_sse_stream_is_read_step_by_step(monkeypatch):
    import frontend.streamlit_app as ui

    _serve(
        monkeypatch,
        ui,
        'data: {"content": {"parts": [{"functionCall": {"name": "list_projects", "args": {}}}]}}\n\n'
        'data: {"content": {"parts": [{"text": "20 projets."}]}}\n\n',
    )
    seen: list = []
    events = ui.run_agent("s", "q", on_event=seen.append)
    assert len(events) == 2 and seen == events


def test_sse_error_event_is_raised(monkeypatch):
    import pytest

    import frontend.streamlit_app as ui

    _serve(monkeypatch, ui, 'data: {"error": "AllModelsUnavailableError: saturé"}\n\n')
    with pytest.raises(ui.AgentError, match="saturé"):
        ui.run_agent("s", "q")
