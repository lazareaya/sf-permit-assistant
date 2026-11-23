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
    assert text.endswith("OK") and "Gemini saturé" in text
