import chainlit as cl
from google.adk.memory import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent

APP_NAME = "sre-agent"
_session_service = InMemorySessionService()
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
