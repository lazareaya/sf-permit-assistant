"""Baseline required by the course: a *single-prompt* assistant.

Same model, same scope, same disclaimer, but **no tools, no skills, no RAG,
no guardrails, no database**. Served by the same FastAPI server under the app
name ``baseline`` so both are evaluated on the same 25 scenarios and judge.
"""

import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

DISCLAIMER = "Information générale, pas un avis juridique. Vérifier auprès du Department of Building Inspection."

root_agent = Agent(
    name="baseline_single_prompt",
    model=Gemini(model=os.getenv("AGENT_MODEL", "gemini-3.8-flash")),
    instruction=(
        "Tu es l'assistant permis de construire d'un cabinet d'architectes à San Francisco. "
        "Tu traites 3 types de demandes : les permis existants à une adresse de San Francisco, "
        "les documents requis pour un type de travaux (cuisine, salle de bain, ADU, toiture, "
        "solaire, fenêtres) et la préparation du dossier d'un projet du cabinet. Refuse poliment "
        "toute autre demande. Réponds en français et termine chaque réponse par : "
        f"« ⚠️ {DISCLAIMER} »"
    ),
    generate_content_config=types.GenerateContentConfig(temperature=0),
)

app = App(root_agent=root_agent, name="baseline")
