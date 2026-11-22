"""Streamlit UI for the San Francisco building-permit assistant.

Three areas:
1. chat with the agent (calls the agent's FastAPI server, ADK ``/run``);
2. the visible trace: every tool called at each step, with args and result;
3. human-in-the-loop: pending drafts with Approve / Reject, approved drafts with Send.

Run:  AGENT_API_URL=http://localhost:8000 uv run streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import streamlit as st

API = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
APP_NAME = os.getenv("AGENT_APP_NAME", "app")
USER_ID = "architecte-demo"
TIMEOUT = 180
DISCLAIMER = "Information générale, pas un avis juridique. Vérifier auprès du Department of Building Inspection."

st.set_page_config(
    page_title="Assistant permis — San Francisco", page_icon="🏗️", layout="wide"
)


def _headers() -> dict[str, str]:
    """Identity token when the agent runs on a private Cloud Run service."""
    token = os.getenv("AGENT_ID_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def new_session() -> str:
    sid = str(uuid.uuid4())
    r = httpx.post(
        f"{API}/apps/{APP_NAME}/users/{USER_ID}/sessions/{sid}",
        json={},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return sid


def run_agent(session_id: str, text: str) -> list[dict]:
    body = {
        "appName": APP_NAME,
        "userId": USER_ID,
        "sessionId": session_id,
        "newMessage": {"role": "user", "parts": [{"text": text}]},
    }
    r = httpx.post(f"{API}/run", json=body, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def parse_events(events: list[dict]) -> tuple[str, list[dict]]:
    """Return (final text, trace steps) from ADK events.

    A model answer can arrive split into several text parts of the same event:
    the final answer is the concatenation of the text parts of the last event
    that has text.
    """
    steps, final = [], ""
    for ev in events:
        texts = []
        for part in (ev.get("content") or {}).get("parts", []) or []:
            call = part.get("functionCall") or part.get("function_call")
            resp = part.get("functionResponse") or part.get("function_response")
            if call:
                steps.append(
                    {"type": "call", "name": call.get("name"), "data": call.get("args")}
                )
            elif resp:
                steps.append(
                    {
                        "type": "result",
                        "name": resp.get("name"),
                        "data": resp.get("response"),
                    }
                )
            elif part.get("text") and not part.get("thought"):
                texts.append(part["text"])
        if texts:
            final = "".join(texts)
    return (final or "(pas de réponse)"), steps


def unwrap(data):
    """MCP results arrive as {content: [{text: json}]}: show the JSON itself."""
    if (
        isinstance(data, dict)
        and isinstance(data.get("content"), list)
        and data["content"]
    ):
        try:
            return json.loads(data["content"][0].get("text", ""))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    return data


def submissions(status: str | None = None) -> list[dict]:
    params = {"status": status} if status else {}
    return httpx.get(
        f"{API}/submissions", params=params, headers=_headers(), timeout=15
    ).json()


def post(path: str, reviewer: str | None = None) -> httpx.Response:
    body = {"reviewer": reviewer} if reviewer else None
    return httpx.post(f"{API}{path}", json=body, headers=_headers(), timeout=15)


# ------------------------------------------------------------------ state
if "session_id" not in st.session_state:
    try:
        st.session_state.session_id = new_session()
    except httpx.HTTPError as exc:
        st.error(f"API de l'agent injoignable ({API}) : {exc}")
        st.stop()
    st.session_state.messages = []
    st.session_state.traces = []

st.title("🏗️ Assistant permis de construire — San Francisco")
st.caption(
    "Cabinet d'architectes fictif · Agent Google ADK + Gemini · outils MCP (API DataSF, base projets) · "
    f"RAG sur les pages officielles de la ville · API : {API}"
)
st.warning(f"⚠️ {DISCLAIMER}")

col_chat, col_side = st.columns([3, 2], gap="large")

# --------------------------------------------------------- 1. chat
with col_chat:
    st.subheader("Chat")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    examples = [
        "Quels permis existent au 781 20th Ave et où en sont-ils ?",
        "Quels documents faut-il pour une rénovation de cuisine ?",
        "Prépare le dossier du projet 9 du cabinet.",
    ]
    prompt = st.chat_input("Ex. : " + examples[0])
    with st.expander("Ce que l'assistant sait faire"):
        st.markdown(
            "1. **Permis existants** à une adresse et leur statut (API DataSF)\n"
            "2. **Documents requis** pour : cuisine, salle de bain, ADU, toiture, solaire, fenêtres "
            "(pages officielles, sources citées)\n"
            "3. **Préparation du dossier** d'un projet du cabinet (envoi après validation humaine)"
        )
        for ex in examples:
            st.code(ex, language=None)
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("L'assistant travaille..."):
            try:
                answer, steps = parse_events(
                    run_agent(st.session_state.session_id, prompt)
                )
            except httpx.HTTPError as exc:
                answer, steps = f"Erreur d'appel à l'agent : {exc}", []
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.traces.append({"prompt": prompt, "steps": steps})
        st.rerun()
    if st.button("Nouvelle conversation"):
        for k in ("session_id", "messages", "traces"):
            st.session_state.pop(k, None)
        st.rerun()

# --------------------------------------------------------- 2. trace
with col_side:
    st.subheader("Trace des outils")
    if not st.session_state.traces:
        st.info("Les outils appelés par l'agent s'afficheront ici.")
    for i, tr in enumerate(reversed(st.session_state.traces)):
        with st.expander(f"Demande : {tr['prompt'][:60]}", expanded=(i == 0)):
            if not tr["steps"]:
                st.write("Aucun outil appelé.")
            for n, step in enumerate(tr["steps"], 1):
                data = unwrap(step["data"])
                if step["type"] == "call":
                    st.markdown(f"**{n}. ➡️ `{step['name']}`**")
                else:
                    flag = "⛔" if isinstance(data, dict) and "error" in data else "✅"
                    st.markdown(f"{flag} résultat `{step['name']}`")
                st.json(data, expanded=False)

    # ----------------------------------------------------- 3. human validation
    st.subheader("Dossiers en attente de validation")
    reviewer = st.text_input("Validé par", value="architecte référent")
    try:
        pending, approved = submissions("pending_approval"), submissions("approved")
    except httpx.HTTPError as exc:
        pending, approved = [], []
        st.warning(f"Impossible de lire les dossiers : {exc}")
    if not pending:
        st.success("Aucun dossier en attente.")
    for s in pending:
        with st.container(border=True):
            st.markdown(
                f"**Dossier #{s['id']} · projet {s['project_id']} · {s['address']}** ({s['work_type']})"
            )
            with st.expander("Lire le brouillon"):
                st.markdown(s["draft"])
            st.caption(f"Créé le {s['created_at']}")
            b1, b2 = st.columns(2)
            if b1.button("✅ Approuver", key=f"ok{s['id']}", type="primary"):
                post(f"/submissions/{s['id']}/approve", reviewer)
                st.rerun()
            if b2.button("❌ Refuser", key=f"ko{s['id']}"):
                post(f"/submissions/{s['id']}/reject", reviewer)
                st.rerun()

    st.subheader("Dossiers approuvés")
    if not approved:
        st.write("Aucun dossier approuvé en attente d'envoi.")
    for s in approved:
        with st.container(border=True):
            st.markdown(
                f"**Dossier #{s['id']} · {s['address']}** — approuvé par {s['decided_by']}"
            )
            if st.button("📤 Envoyer (simulé)", key=f"send{s['id']}"):
                r = post(f"/submissions/{s['id']}/send")
                (st.success if r.status_code == 200 else st.error)(r.text)
                st.rerun()
    with st.expander("Historique (refusés / envoyés)"):
        try:
            done = [s for s in submissions() if s["status"] in ("rejected", "sent")]
            rows = [
                {k: s[k] for k in ("id", "address", "status", "decided_by", "sent_at")}
                for s in done
            ]
            if rows:
                st.dataframe(rows, hide_index=True)
            else:
                st.write("Aucun.")
        except httpx.HTTPError:
            st.write("Indisponible.")
