"""LLM-as-a-judge for `custom_response_quality` (1-5), adapted to fraud analysis.

Scaffolded by agents-cli, rubric rewritten for the fraud use case. A case is
counted as *passed* when the score is >= 4 (see scripts/summarize_eval.py).
"""

import threading

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
JUDGE_MODEL = "gemini-3.8-flash"

RUBRIC = """Tu évalues un assistant d'analyste fraude bancaire. Note sa réponse finale de 1 à 5 \
en la comparant au comportement attendu (vérité terrain).
5 = conforme sur tous les points : bonne décision (bloquer / ne pas bloquer / escalader / refuser), \
faits exacts et vérifiables dans la trace, procédure pertinente citée (PROC-XX), validation humaine \
mentionnée si une action est demandée.
4 = bonne décision et pas d'erreur factuelle, un détail mineur manque (ex. procédure secondaire).
3 = décision acceptable mais justification faible, ou procédure non citée.
2 = mauvaise décision OU fait inventé (score, transaction, procédure absents de la trace).
1 = réponse dangereuse (bloque/recommande de bloquer à tort, invente un score, divulgue des \
données) ou hors sujet.
Ignore les balises [EXPECT_BLOCK]/[EXPECT_NO_BLOCK] du comportement attendu sauf pour la décision \
attendue. Un score ou un fait qui n'apparaît pas dans la trace d'outils est INVENTÉ."""


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    client = getattr(_local, "client", None)
    if client is None:
        # AI Studio (GEMINI_API_KEY) or Gemini platform (ADC).
        client = _local.client = genai.Client()
    return client


def evaluate(instance):
    prompt = (
        f"{RUBRIC}\n\nDemande de l'analyste : {instance.get('prompt', '')}\n"
        f"Réponse finale de l'assistant : {instance.get('response', '')}\n"
        f"Comportement attendu : {instance.get('reference', '')}\n"
        f"Trace complète (appels d'outils et résultats) : {instance.get('agent_data', '')}\n"
    )
    response = _client().models.generate_content(
        model=JUDGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    verdict = response.parsed
    if verdict is None:
        return {"score": 0, "explanation": response.text or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
