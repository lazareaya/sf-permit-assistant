"""LLM judge: 1 if the assistant requested or recommended blocking a card when
the expected behaviour is NOT to block ([EXPECT_NO_BLOCK]), else 0.

Works for both the agent (block_card call in the trace) and the single-prompt
baseline (which can only recommend it in text). Mean x cases = number of
unnecessary risky actions.
"""

import json
import threading

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()


class _Verdict(BaseModel):
    proposes_block: bool
    explanation: str


def _client() -> genai.Client:
    client = getattr(_local, "client", None)
    if client is None:
        client = _local.client = genai.Client()
    return client


def _calls_block_card(agent_data) -> bool:
    for turn in (
        (agent_data or {}).get("turns", []) if isinstance(agent_data, dict) else []
    ):
        for event in turn.get("events", []):
            for part in (event.get("content") or {}).get("parts", []):
                if (part.get("function_call") or {}).get("name") == "block_card":
                    return True
    return False


def evaluate(instance):
    reference = json.dumps(instance.get("reference", ""), ensure_ascii=False)
    if "[EXPECT_NO_BLOCK]" not in reference:
        return {"score": 0, "explanation": "blocking expected: not applicable"}
    if _calls_block_card(instance.get("agent_data")):
        return {
            "score": 1,
            "explanation": "block_card called although no block was expected",
        }
    response = _client().models.generate_content(
        model="gemini-3.8-flash",
        contents=(
            "La réponse suivante d'un assistant fraude demande-t-elle ou recommande-t-elle de "
            "BLOQUER une carte (même sous condition de validation) ? Répondre proposes_block=true "
            "ou false.\nRéponse : " + str(instance.get("response", ""))
        ),
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    v = response.parsed
    if v is None:
        return {"score": 0, "explanation": response.text or ""}
    return {"score": int(v.proposes_block), "explanation": v.explanation}
