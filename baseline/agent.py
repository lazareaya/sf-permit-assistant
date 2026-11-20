"""Baseline required by the course: a *single-prompt* assistant.

Same model, same task description and same output format as the fraud analyst
agent, but **no tools, no skills, no RAG, no guardrails**. It is served by the
same FastAPI server under the app name ``baseline`` so both are evaluated on
the same 25 scenarios with the same LLM judge.
"""

import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

root_agent = Agent(
    name="baseline_single_prompt",
    model=Gemini(model=os.getenv("AGENT_MODEL", "gemini-3.8-flash")),
    instruction=(
        "Tu es un assistant pour analystes fraude d'une banque. On te soumet des alertes de "
        "fraude carte (identifiant de carte CARD-00000 ou de transaction). Analyse la situation "
        "et propose une action (bloquer la carte, contacter le client, escalader, ne rien faire). "
        "Réponds en français avec : **Synthèse** / **Faits** / **Procédure appliquée** / "
        "**Action proposée**."
    ),
    generate_content_config=types.GenerateContentConfig(temperature=0),
)

app = App(root_agent=root_agent, name="baseline")
