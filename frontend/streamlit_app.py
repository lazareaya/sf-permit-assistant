"""Streamlit UI for the fraud analyst agent.

Three areas:
1. chat with the agent (calls the agent's FastAPI server, ADK ``/run``);
2. the visible trace: every tool called at each step, with args and result;
3. human-in-the-loop: Approve / Reject buttons for pending actions.

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
USER_ID = "analyste-demo"
TIMEOUT = 180

st.set_page_config(page_title="Assistant analyste fraude", page_icon="🛡️", layout="wide")


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
    """Return (final text, trace steps) from ADK events."""
    steps, texts = [], []
    for ev in events:
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
    return (texts[-1] if texts else "(pas de réponse)"), steps


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


# ------------------------------------------------------------------ state
if "session_id" not in st.session_state:
    try:
        st.session_state.session_id = new_session()
    except httpx.HTTPError as exc:
        st.error(f"API de l'agent injoignable ({API}) : {exc}")
        st.stop()
    st.session_state.messages = []
    st.session_state.traces = []

st.title("🛡️ Assistant analyste fraude")
st.caption(f"Agent Google ADK + Gemini · outils MCP · RAG procédures · API : {API}")

col_chat, col_side = st.columns([3, 2], gap="large")

# --------------------------------------------------------- 1. chat
with col_chat:
    st.subheader("Chat")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    examples = [
        "Alerte fraude sur la transaction 110613. Peux-tu instruire le dossier ?",
        "Est-ce que la transaction 111410 est frauduleuse ?",
        "Bloque la carte CARD-99999.",
    ]
    prompt = st.chat_input("Ex. : " + examples[0])
    with st.expander("Exemples"):
        for ex in examples:
            st.code(ex, language=None)
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("L'agent enquête..."):
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
                    st.json(data, expanded=False)
                else:
                    flag = "⛔" if isinstance(data, dict) and "error" in data else "✅"
                    st.markdown(f"{flag} résultat `{step['name']}`")
                    st.json(data, expanded=False)

    # ----------------------------------------------------- 3. human validation
    st.subheader("Actions en attente de validation")
    try:
        pending = httpx.get(
            f"{API}/actions",
            params={"status": "pending_approval"},
            headers=_headers(),
            timeout=15,
        ).json()
    except httpx.HTTPError as exc:
        pending = []
        st.warning(f"Impossible de lire les actions : {exc}")
    if not pending:
        st.success("Aucune action en attente.")
    reviewer = st.text_input("Validé par", value="analyste N1")
    for a in pending:
        with st.container(border=True):
            st.markdown(
                f"**#{a['action_id']} · {a['action_type']} · {a['card_id']}**"
                f" (transaction {a.get('tx_id') or '—'})"
            )
            st.write(a["justification"])
            st.caption(
                f"Procédure citée : {a['procedure_id']} · demandé par {a['requested_by']} "
                f"le {a['created_at']}"
            )
            b1, b2 = st.columns(2)
            if b1.button("✅ Approuver", key=f"ok{a['action_id']}", type="primary"):
                httpx.post(
                    f"{API}/actions/{a['action_id']}/approve",
                    json={"reviewer": reviewer},
                    headers=_headers(),
                    timeout=15,
                )
                st.rerun()
            if b2.button("❌ Refuser", key=f"ko{a['action_id']}"):
                httpx.post(
                    f"{API}/actions/{a['action_id']}/reject",
                    json={"reviewer": reviewer},
                    headers=_headers(),
                    timeout=15,
                )
                st.rerun()
    with st.expander("Historique des décisions"):
        try:
            done = [
                a
                for a in httpx.get(
                    f"{API}/actions", headers=_headers(), timeout=15
                ).json()
                if a["status"] != "pending_approval"
            ]
            st.dataframe(done, hide_index=True) if done else st.write(
                "Aucune décision."
            )
        except httpx.HTTPError:
            st.write("Indisponible.")
