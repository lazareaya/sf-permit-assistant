"""Record real agent answers to the demo questions (plan B for live demos).

The Streamlit UI replays them when Gemini's free tier is saturated, or in
"mode démo hors ligne". Run against the deployed agent:

    AGENT_API_URL=https://...run.app AGENT_ID_TOKEN=$(gcloud auth print-identity-token) \
        uv run python scripts/record_demo.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.streamlit_app import parse_events, save_replay

API = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("AGENT_ID_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

QUESTIONS = [
    "Quels permis ont été déposés au 1 Dr Carlton B Goodlett Pl ?",
    "Quels permis existent au 781 20th Ave et où en sont-ils ?",
    "Quels documents faut-il pour une rénovation de cuisine ?",
    "Quels documents faut-il pour poser des panneaux solaires ?",
    "Prépare le dossier du projet 9 du cabinet.",
    "Quel temps fera-t-il demain ?",
]


def ask(question: str) -> list[dict]:
    sid = str(uuid.uuid4())
    httpx.post(
        f"{API}/apps/app/users/demo-recorder/sessions/{sid}",
        json={},
        headers=HEADERS,
        timeout=30,
    ).raise_for_status()
    body = {
        "appName": "app",
        "userId": "demo-recorder",
        "sessionId": sid,
        "newMessage": {"role": "user", "parts": [{"text": question}]},
    }
    r = httpx.post(f"{API}/run", json=body, headers=HEADERS, timeout=180)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    for q in QUESTIONS:
        try:
            events = ask(q)
        except httpx.HTTPError as exc:
            print(f"ÉCHEC  {q} ({exc})")
            continue
        text, steps = parse_events(events)
        if text == "(pas de réponse)":
            print(f"VIDE   {q}")
            continue
        save_replay(q, events)
        print(f"OK     {q}  ({len(steps)} étapes d'outils)")
