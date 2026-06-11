"""Chainlit UI as a thin client of the deployed Reasoning Engine.

Environment / config:
    AGENT_ENGINE_RESOURCE  Optional override for the engine resource name.
                           Defaults to `remote_agent_runtime_id` in
                           sre-agent/deployment_metadata.json.
    CHAT_USER_ID           Optional override for the Memory Bank user_id.
                           Defaults to "sre-agent" — must match the value the
                           Jira webhook uses (see functions/jira_webhook/main.py
                           `_AGENT_USER_ID`).
"""

import json
import os
from pathlib import Path

import chainlit as cl
import vertexai
from vertexai import agent_engines

SHARED_USER_ID = os.environ.get("CHAT_USER_ID", "sre-agent")


def _resolve_engine_resource() -> str:
    if env := os.environ.get("AGENT_ENGINE_RESOURCE"):
        return env
    meta = Path(__file__).resolve().parent.parent / "deployment_metadata.json"
    if not meta.exists():
        raise RuntimeError(
            "No deployment_metadata.json found. Run `make deploy` first, or set "
            "AGENT_ENGINE_RESOURCE to projects/<num>/locations/<loc>/reasoningEngines/<id>."
        )
    with meta.open() as f:
        resource = json.load(f).get("remote_agent_runtime_id", "")
    if not resource:
        raise RuntimeError("remote_agent_runtime_id missing from deployment_metadata.json.")
    return resource


_RESOURCE = _resolve_engine_resource()
# resource format: projects/<num>/locations/<loc>/reasoningEngines/<id>
_parts = _RESOURCE.split("/")
vertexai.init(project=_parts[1], location=_parts[3])
_engine = agent_engines.get(_RESOURCE)
print(f"[chainlit] Connected to engine {_RESOURCE} as user_id={SHARED_USER_ID}")


@cl.on_chat_start
async def on_chat_start():
    session = _engine.create_session(user_id=SHARED_USER_ID)
    cl.user_session.set("session_id", session["id"])


@cl.on_message
async def main(message: cl.Message):
    session_id: str = cl.user_session.get("session_id")
    msg = cl.Message(content="")

    async for event in _engine.async_stream_query(
        user_id=SHARED_USER_ID,
        session_id=session_id,
        message=message.content,
    ):
        content = event.get("content") if isinstance(event, dict) else None
        if not content or content.get("role") != "model":
            continue
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                await msg.stream_token(text)

    await msg.update()
