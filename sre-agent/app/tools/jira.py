# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
"""Jira tool - post investigation findings back to a Jira ticket.

Jira credentials are loaded from a single Secret Manager secret containing JSON:
    {"base_url": "...", "email": "...", "api_token": "...", "webhook_secret": "..."}

Required env vars at runtime:
    GOOGLE_CLOUD_PROJECT   - project hosting the secret
    JIRA_SECRET_NAME       - secret short name (default: "jira-webhook")
"""

from __future__ import annotations

import json
import logging
import os

import requests
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

_DEFAULT_SECRET_NAME = "jira-webhook"
_jira_creds: dict | None = None


def _get_jira_creds() -> dict:
    """Fetch and cache Jira credentials from Secret Manager."""
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


def post_jira_comment(issue_key: str, comment: str) -> str:
    """Post a comment on a Jira issue.

    Use this to report investigation findings, root cause analysis, or
    remediation recommendations back to the Jira ticket that triggered this
    alert.

    Args:
        issue_key: The Jira issue key (e.g. "SRE-123").
        comment:   The comment body. Plain text.

    Returns:
        Success message with comment URL, or an error description.
    """
    creds = _get_jira_creds()
    base_url = creds["base_url"].rstrip("/")
    email = creds["email"]
    api_token = creds["api_token"]

    url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment}],
                }
            ],
        }
    }

    resp = requests.post(
        url,
        json=payload,
        auth=(email, api_token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=10,
    )

    if resp.status_code == 201:
        comment_id = resp.json().get("id")
        comment_url = f"{base_url}/browse/{issue_key}?focusedCommentId={comment_id}"
        logger.info("[Jira] Comment posted: issue=%s id=%s", issue_key, comment_id)
        return f"Comment posted successfully: {comment_url}"

    logger.error(
        "[Jira] Failed to post comment: issue=%s status=%s body=%s",
        issue_key,
        resp.status_code,
        resp.text,
    )
    return f"Failed to post comment: HTTP {resp.status_code} - {resp.text}"
