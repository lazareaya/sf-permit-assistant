"""Streamlit UI for the San Francisco building-permit assistant.

Three areas:
1. chat with the agent (calls the agent's FastAPI server, ADK ``/run``);
2. the visible trace: every tool called at each step, with args and result;
3. human-in-the-loop: pending drafts with Approve / Reject, approved drafts with Send.

Free-tier resilience: every successful answer is recorded in
``frontend/demo_replays.json``. If Gemini is saturated (timeout or 5xx), the
recorded answer to the same question is shown, clearly labelled; the
"mode démo hors ligne" toggle replays recorded answers only.

Run:  AGENT_API_URL=http://localhost:8000 uv run streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import streamlit as st

API = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
APP_NAME = os.getenv("AGENT_APP_NAME", "app")
USER_ID = "architecte-demo"
TIMEOUT = float(os.getenv("AGENT_TIMEOUT_S", "120"))
REPLAYS_PATH = Path(
    os.getenv("DEMO_REPLAYS", Path(__file__).with_name("demo_replays.json"))
)
SKILL_LABELS = {
    "permit_search": "recherche de permis",
    "document_requirements": "documents requis",
    "submission_prep": "préparation de dossier",
}
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


class AgentError(RuntimeError):
    """The agent run failed on the server (error event of the SSE stream)."""


def run_agent(session_id: str, text: str, on_event=None) -> list[dict]:
    """Run the agent through ADK ``/run_sse``: events arrive step by step."""
    body = {
        "appName": APP_NAME,
        "userId": USER_ID,
        "sessionId": session_id,
        "newMessage": {"role": "user", "parts": [{"text": text}]},
    }
    events: list[dict] = []
    with httpx.stream(
        "POST", f"{API}/run_sse", json=body, headers=_headers(), timeout=TIMEOUT
    ) as r:
        if r.status_code >= 400:
            r.read()
            r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if "error" in ev and "content" not in ev:
                raise AgentError(ev["error"])
            events.append(ev)
            if on_event:
                on_event(ev)
    return events


def describe_event(ev: dict) -> str | None:
    """Progress label for one agent event (None: nothing to show)."""
    for part in (ev.get("content") or {}).get("parts", []) or []:
        call = part.get("functionCall") or part.get("function_call")
        resp = part.get("functionResponse") or part.get("function_response")
        if call:
            name, args = call.get("name"), call.get("args") or {}
            if name == "activate_skill":
                skill = args.get("skill_name", "")
                return f"🧭 Choix de la compétence : {SKILL_LABELS.get(skill, skill)}"
            if name == "search_permits":
                return (
                    f"🏛️ Recherche des permis au {args.get('address', '?')} "
                    "(API DataSF de la ville)…"
                )
            if name == "search_city_docs":
                return (
                    "📚 Recherche dans les pages officielles de la ville : "
                    f"« {args.get('question', '')} »…"
                )
            if name == "list_projects":
                return "🗂️ Lecture de la liste des projets du cabinet…"
            if name == "get_project":
                return f"🗂️ Lecture du projet n°{args.get('project_id', '?')}…"
            if name == "create_submission_draft":
                return (
                    "📝 Rédaction du brouillon de dossier (validation humaine requise)…"
                )
            if name == "send_submission":
                return f"📤 Tentative d'envoi du dossier n°{args.get('submission_id', '?')}…"
            return f"🔧 Appel de l'outil {name}…"
        if resp:
            data = unwrap(resp.get("response"))
            name = resp.get("name")
            if isinstance(data, dict) and data.get("error"):
                return f"⚠️ {name} : {data['error']} — {data.get('message', '')}"[:200]
            if isinstance(data, dict) and "permit_count" in data:
                return f"✅ {data['permit_count']} permis trouvés · Gemini analyse les résultats…"
            if isinstance(data, dict) and "passages" in data:
                n = len(data["passages"])
                found = (
                    f"{n} passage(s) pertinent(s)" if n else "aucun passage pertinent"
                )
                return f"✅ {found} · Gemini analyse les résultats…"
            if name == "activate_skill":
                return "🧠 Compétence activée · Gemini prépare la recherche…"
            return f"✅ Résultat de {name} reçu · Gemini analyse les résultats…"
        if part.get("text") and not part.get("thought"):
            return "✍️ Réponse rédigée"
    return None


def explain_failure(exc: Exception) -> str:
    """Why the agent could not answer, in plain French."""
    if isinstance(exc, AgentError):
        msg = str(exc)
        if "AllModelsUnavailableError" in msg:
            return (
                "⏳ Gemini (offre gratuite) n'a pas pu répondre. "
                + msg.split(": ", 1)[-1]
            )
        return f"⚠️ L'agent a rencontré une erreur : {msg}"
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"⏳ Pas de réponse de l'agent en {TIMEOUT:.0f} s : Gemini (offre gratuite) "
            "est très lent ou saturé. Réessayez dans un instant."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return (
                "🔒 Cloud Run refuse l'accès : le jeton d'identité a expiré (il dure "
                "1 h). Relancez l'interface avec un nouveau jeton."
            )
        if code == 404:
            return "⚠️ Conversation introuvable côté agent : cliquez sur « Nouvelle conversation »."
        if code == 429:
            return "⏳ Trop de requêtes vers l'agent : réessayez dans un instant."
        return f"⚠️ Erreur serveur de l'agent (HTTP {code})."
    if isinstance(exc, httpx.HTTPError):
        return f"🔌 Agent injoignable ({API}) : {exc}"
    return f"⚠️ Erreur inattendue : {exc}"


# ----------------------------------------------------------- recorded answers
def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def load_replays() -> dict:
    try:
        return json.loads(REPLAYS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_replay(prompt: str, events: list[dict]) -> None:
    replays = load_replays()
    replays[_norm(prompt)] = {
        "prompt": prompt,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "events": events,
    }
    try:
        REPLAYS_PATH.write_text(
            json.dumps(replays, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError:
        pass  # read-only file system: recording is best effort


def replay_for(prompt: str) -> dict | None:
    return load_replays().get(_norm(prompt))


def answer(prompt: str, offline: bool, progress=None) -> tuple[str, list[dict]]:
    """Live answer from the agent; recorded answer if it cannot answer.

    ``progress(label)`` is called at each step of the agent run, and with a
    label starting with "❌" when the run fails.
    """
    if not offline:
        try:
            try:
                events = run_agent(
                    st.session_state.session_id,
                    prompt,
                    on_event=lambda ev: (
                        progress and (lbl := describe_event(ev)) and progress(lbl)
                    ),
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                # The instance that held the conversation was recycled: new session.
                st.session_state.session_id = new_session()
                events = run_agent(st.session_state.session_id, prompt)
            text, steps = parse_events(events)
            if text != "(pas de réponse)":
                save_replay(prompt, events)
            return text, steps
        except (AgentError, httpx.HTTPError) as exc:
            problem = explain_failure(exc)
    else:
        problem = (
            "Mode démo hors ligne : aucune réponse enregistrée pour cette question."
        )
    if progress and not offline:
        progress("❌ " + problem)
    rec = replay_for(prompt)
    if rec is None:
        return problem, []
    text, steps = parse_events(rec["events"])
    if offline:
        note = (
            f"*📼 Réponse réelle de l'agent enregistrée le {rec['recorded_at']}.*\n\n"
        )
    else:
        note = (
            f"{problem}\n\n*📼 Voici la réponse réelle de l'agent à cette question, "
            f"enregistrée le {rec['recorded_at']} :*\n\n"
        )
    return note + text, steps


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
with st.sidebar:
    offline = st.toggle(
        "Mode démo hors ligne",
        help="Rejoue les réponses réelles enregistrées, sans appeler Gemini.",
    )
    recorded = [r["prompt"] for r in load_replays().values()]
    st.caption(f"{len(recorded)} réponse(s) enregistrée(s)")
    for q in recorded:
        st.code(q, language=None)

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
        with st.status("🧠 Gemini analyse la question…", expanded=True) as status:
            failed = []

            def progress(label: str) -> None:
                if label.startswith("❌"):
                    failed.append(label)
                status.update(label=label[:120])
                status.write(label)

            reply, steps = answer(prompt, offline, progress)
            if failed:
                status.update(label="❌ L'agent n'a pas pu répondre", state="error")
            else:
                status.update(
                    label="✅ Réponse prête", state="complete", expanded=False
                )
        st.session_state.messages.append({"role": "assistant", "content": reply})
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
