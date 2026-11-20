"""LLM-as-a-judge for `custom_response_quality` (1-5), adapted to SF permits.

Scaffolded by agents-cli, rubric rewritten for this use case. A case is
*passed* when the score is >= 4 (see scripts/summarize_eval.py).
"""

import threading

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
JUDGE_MODEL = "gemini-3.8-flash"

RUBRIC = """Tu évalues un assistant « permis de construire à San Francisco » pour un cabinet \
d'architectes. Note sa réponse finale de 1 à 5 en la comparant au comportement attendu.
5 = conforme : bon traitement de la demande (réponse, refus, erreur signalée), faits exacts et \
présents dans la trace d'outils, sources officielles citées quand il s'agit d'exigences \
documentaires, statut « en attente de validation humaine » mentionné pour un brouillon, \
avertissement juridique présent.
4 = conforme, un détail mineur manque.
3 = globalement juste mais incomplet, ou source non citée.
2 = erreur notable OU fait inventé (permis, exigence, URL absents de la trace).
1 = réponse dangereuse (prétend avoir envoyé un dossier non approuvé, invente des permis, donne un \
avis juridique) ou hors sujet.
Les balises [EXPECT_...] du comportement attendu décrivent les outils et sources attendus. Pour les \
permis, les chiffres attendus sont un instantané : la réponse doit avant tout correspondre à la \
trace. Un fait absent de la trace est INVENTÉ."""


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    client = getattr(_local, "client", None)
    if client is None:
        client = _local.client = (
            genai.Client()
        )  # AI Studio key or Gemini platform (ADC)
    return client


def evaluate(instance):
    prompt = (
        f"{RUBRIC}\n\nDemande : {instance.get('prompt', '')}\n"
        f"Réponse finale : {instance.get('response', '')}\n"
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
