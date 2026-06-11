import json
import os
from pathlib import Path

import chainlit as cl
from google.adk.memory import InMemoryMemoryService, VertexAiMemoryBankService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent

APP_NAME = "sre-agent"


def _resolve_agent_engine_id() -> str | None:
    """Pull the deployed engine ID from deployment_metadata.json (matches the
    pattern in the Makefile's `dev` target). Falls back to env or None for
    pure-local testing."""
    env = os.environ.get("AGENT_ENGINE_ID")
    if env:
        return env.split("/")[-1]
    meta = Path(__file__).resolve().parent.parent / "deployment_metadata.json"
    if meta.exists():
        with meta.open() as f:
            data = json.load(f)
        full = data.get("remote_agent_runtime_id", "")
        if full:
            return full.split("/")[-1]
    return None


_session_service = InMemorySessionService()

_engine_id = _resolve_agent_engine_id()
if _engine_id:
    import google.auth

    _, _project = google.auth.default()
    _location = os.environ.get("GOOGLE_CLOUD_REGION", "us-east1")
    print(
        f"[chainlit] Using Vertex Memory Bank: "
        f"project={_project} location={_location} engine={_engine_id}"
    )
    _memory_service = VertexAiMemoryBankService(
        project=_project,
        location=_location,
        agent_engine_id=_engine_id,
    )
else:
    print("[chainlit] No deployed engine found — using InMemoryMemoryService")
    _memory_service = InMemoryMemoryService()


@cl.on_chat_start
async def on_chat_start():
    session = await _session_service.create_session(
        app_name=APP_NAME,
        user_id=cl.user_session.get("id"),
    )
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=_session_service,
        memory_service=_memory_service,
    )
    cl.user_session.set("session_id", session.id)
    cl.user_session.set("runner", runner)


@cl.on_message
async def main(message: cl.Message):
    runner: Runner = cl.user_session.get("runner")
    session_id: str = cl.user_session.get("session_id")
    user_id: str = cl.user_session.get("id")

    user_message = types.Content(
        role="user",
        parts=[types.Part(text=message.content)],
    )

    msg = cl.Message(content="")
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        if event.content and event.content.parts and event.content.role == "model":
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    await msg.stream_token(part.text)

    await msg.update()
