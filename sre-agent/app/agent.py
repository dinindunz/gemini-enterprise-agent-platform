# ruff: noqa
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

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models.anthropic_llm import Claude
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

import os
import google.auth

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# Cloud Logging MCP server (managed by Google). Enabled via `make mcp-setup`.
# Resource name (opaque UUID) is resolved at startup so the code stays portable
# across projects.
_registry = AgentRegistry(project_id=project_id, location="global")
_logging_servers = _registry.list_mcp_servers(
    filter_str='displayName="logging.googleapis.com"'
).get("mcpServers", [])
if not _logging_servers:
    raise RuntimeError(
        "Cloud Logging MCP server is not registered in this project. "
        "Run `make mcp-setup` from sre-agent/."
    )
logging_toolset = _registry.get_mcp_toolset(
    mcp_server_name=_logging_servers[0]["name"],
)


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_events_to_memory(
        events=callback_context.session.events[-5:-1]
    )


root_agent = Agent(
    name="root_agent",
    model=Claude(
        model=f"projects/{project_id}/locations/us-east5/publishers/anthropic/models/claude-sonnet-4-6"
    ),
    instruction=(
        "You are an SRE assistant for project "
        f"{project_id}. Use the Cloud Logging tools to investigate incidents "
        "and answer questions about service behaviour. Always scope queries "
        "with a narrow time window and severity filter; prefer structured "
        "filters (logName, resource.type, severity) over free-text searches."
    ),
    tools=[PreloadMemoryTool(), logging_toolset],
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
