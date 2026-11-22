from frontend.streamlit_app import parse_events


def test_answer_split_in_several_parts_is_joined():
    events = [
        {"content": {"parts": [{"functionCall": {"name": "search_permits", "args": {"address": "781 20th Ave"}}}]}},
        {"content": {"parts": [{"functionResponse": {"name": "search_permits", "response": {"permit_count": 8}}}]}},
        {"content": {"parts": [{"text": "Je ne traite que "}, {"text": "3 types de demandes."}]}},
    ]
    text, steps = parse_events(events)
    assert text == "Je ne traite que 3 types de demandes."
    assert [s["type"] for s in steps] == ["call", "result"]
