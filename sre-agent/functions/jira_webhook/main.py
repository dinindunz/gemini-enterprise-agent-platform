# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
"""Jira webhook receiver (Cloud Functions Gen 2 / Python).

Flow:
    1. Verify the Jira HMAC-SHA256 signature against the shared webhook secret.
    2. Build a prompt summarising the Jira event.
    3. Call the deployed Vertex AI Agent Engine via REST
       (`reasoningEngines:streamQuery`) using ADC. Drain a small portion of the
       stream so the request is dispatched, then return 202.

Required env vars on the Cloud Function:
    GOOGLE_CLOUD_PROJECT       - project hosting the agent runtime and secret.
    AGENT_RUNTIME_RESOURCE     - full resource name, e.g.
        projects/<num>/locations/us-east1/reasoningEngines/<id>
    JIRA_SECRET_NAME           - Secret Manager secret name (default: jira-webhook).
                                 Secret payload (JSON): {base_url, email,
                                 api_token, webhook_secret}.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

import functions_framework
import google.auth
import google.auth.transport.requests
import requests
from google.cloud import secretmanager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_DEFAULT_SECRET_NAME = "jira-webhook"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_AGENT_USER_ID = "sre-agent"

_jira_creds: dict | None = None
_credentials = None


def _get_jira_creds() -> dict:
    global _jira_creds
    if _jira_creds is not None:
        return _jira_creds
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    secret_name = os.environ.get("JIRA_SECRET_NAME", _DEFAULT_SECRET_NAME)
    client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{project}/secrets/{secret_name}/versions/latest"
    payload = client.access_secret_version(name=resource).payload.data.decode()
    _jira_creds = json.loads(payload)
    return _jira_creds


def _get_access_token() -> str:
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(scopes=_SCOPES)
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


def _validate_signature(body: bytes, headers: dict) -> bool:
    signature = headers.get("x-hub-signature-256") or headers.get("x-hub-signature", "")
    if not signature:
        logger.warning("Missing webhook signature header")
        return False
    secret = _get_jira_creds()["webhook_secret"]
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _build_prompt(jira_event: dict) -> str:
    event_type = jira_event.get("webhookEvent", "unknown")
    issue = jira_event.get("issue", {})
    issue_key = issue.get("key", "unknown")
    summary = issue.get("fields", {}).get("summary", "")
    return (
        f"Jira webhook event received: {event_type}. "
        f"Issue: {issue_key} - {summary}. "
        "Investigate the incident, then post your findings back to the issue "
        f"using post_jira_comment with issue_key='{issue_key}'. "
        f"Full event payload: {json.dumps(jira_event)}"
    )


def _create_session(base_url: str, headers: dict, user_id: str) -> str | None:
    """Create a new ADK session and return its id.

    `async_stream_query` is strict about session ids — it raises
    SessionNotFoundError if the id doesn't already exist. The supported pattern
    is to create the session up front via the non-streaming `:query` endpoint.
    """
    resp = requests.post(
        f"{base_url}:query",
        json={"class_method": "create_session", "input": {"user_id": user_id}},
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        logger.error(
            "create_session failed: status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        return None
    output = resp.json().get("output", {})
    session_id = output.get("id") or output.get("session_id")
    if not session_id:
        logger.error("create_session returned no id: %s", resp.text[:500])
        return None
    return session_id


def _invoke_agent(prompt: str, user_id: str) -> None:
    """Create a session, then drive `async_stream_query` to completion."""
    resource = os.environ["AGENT_RUNTIME_RESOURCE"]
    # resource = projects/<num>/locations/<region>/reasoningEngines/<id>
    region = resource.split("/")[3]
    base_url = f"https://{region}-aiplatform.googleapis.com/v1/{resource}"
    headers = {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }

    session_id = _create_session(base_url, headers, user_id)
    if session_id is None:
        return

    body = {
        "class_method": "async_stream_query",
        "input": {
            "user_id": user_id,
            "session_id": session_id,
            "message": prompt,
        },
    }
    # Drain the full stream so the agent run (including tool calls like
    # post_jira_comment) completes before the function returns. Closing the
    # connection early cancels the run on the server side.
    with requests.post(
        f"{base_url}:streamQuery", json=body, headers=headers, stream=True, timeout=300
    ) as resp:
        if resp.status_code != 200:
            logger.error(
                "stream_query rejected: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            return
        for _ in resp.iter_lines():
            pass
        logger.info("Agent run completed user=%s session=%s", user_id, session_id)


@functions_framework.http
def handler(request):
    """HTTPS-triggered Cloud Function entry point."""
    headers = {k.lower(): v for k, v in request.headers.items()}
    body_bytes = request.get_data(cache=False)

    if not _validate_signature(body_bytes, headers):
        logger.warning("Rejecting request: invalid Jira webhook signature")
        return ("Unauthorized", 401)

    try:
        jira_event = json.loads(body_bytes.decode() or "{}")
    except json.JSONDecodeError:
        logger.error("Invalid JSON body in Jira webhook")
        return ("Bad Request", 400)

    user_email = jira_event.get("user", {}).get("emailAddress") or "unknown"
    issue_key = jira_event.get("issue", {}).get("key", "unknown")
    event_type = jira_event.get("webhookEvent", "unknown")
    logger.info(
        "Jira webhook: event=%s issue=%s triggered_by=%s",
        event_type, issue_key, user_email,
    )

    try:
        _invoke_agent(_build_prompt(jira_event), user_id=_AGENT_USER_ID)
    except Exception:
        logger.exception("Unhandled error invoking agent runtime")

    return ("Accepted", 202)
