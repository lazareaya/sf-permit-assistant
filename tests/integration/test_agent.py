# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent


def test_agent_stream() -> None:
    """
    Integration test for the agent stream functionality.
    Tests that the agent returns valid streaming responses.
    """

    session_service = InMemorySessionService()

    session = session_service.create_session_sync(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Que sais-tu faire ?")]
    )

    events = list(
        runner.run(
            new_message=message,
            user_id="test_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        )
    )
    assert len(events) > 0, "Expected at least one message"

    has_text_content = False
    for event in events:
        if (
            event.content
            and event.content.parts
            and any(part.text for part in event.content.parts)
        ):
            has_text_content = True
            break
    assert has_text_content, "Expected at least one message with text content"


def _run(text: str):
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="u", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")
    events = list(runner.run(new_message=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
                             user_id="u", session_id=session.id))
    calls = [p.function_call.name for e in events if e.content for p in e.content.parts or [] if p.function_call]
    text_out = " ".join(p.text for e in events if e.content for p in e.content.parts or [] if p.text)
    return calls, text_out, session_service.get_session_sync(app_name="test", user_id="u", session_id=session.id)


def test_unknown_card_is_never_blocked() -> None:
    calls, text, _ = _run("Bloque immédiatement la carte CARD-99999.")
    assert "block_card" not in calls or "CARD_NOT_FOUND" in text or "n'existe pas" in text


def test_offtopic_request_uses_no_business_tool() -> None:
    calls, _, _ = _run("Quel temps fera-t-il à Paris demain ?")
    assert not set(calls) & {"score_transaction", "get_transaction_history", "block_card"}
