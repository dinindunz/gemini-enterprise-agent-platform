"""Create a Jira issue from jira.md.

Reads jira.md alongside this script, parses the Summary and Description
sections, and creates an issue in the project named by JIRA_PROJECT_KEY
using credentials from .env.

Usage:
    python tests/scenarios/slow_db_queries/post_jira.py
    python tests/scenarios/slow_db_queries/post_jira.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_MD = Path(__file__).parent / "jira.md"
ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Task")


def _parse_jira_md(text: str) -> tuple[str, str]:
    """Split jira.md into (summary, description).

    Format:
        Summary:
          <one line>

        Description:
          <one or more lines>
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not line.startswith(" "):
            current = stripped[:-1].lower()
            sections[current] = []
            continue
        if current is None:
            continue
        sections[current].append(line[2:] if line.startswith("  ") else line)

    summary_lines = [ln for ln in sections.get("summary", []) if ln.strip()]
    if not summary_lines:
        raise ValueError("jira.md missing Summary content")
    summary = summary_lines[0].strip()

    desc_lines = sections.get("description", [])
    while desc_lines and not desc_lines[0].strip():
        desc_lines.pop(0)
    while desc_lines and not desc_lines[-1].strip():
        desc_lines.pop()
    description = "\n".join(desc_lines)
    if not description:
        raise ValueError("jira.md missing Description content")

    return summary, description


def _to_adf(description: str) -> dict:
    """Convert plain-text description into Atlassian Document Format."""
    paragraphs = [p for p in description.split("\n\n") if p.strip()]
    content = []
    for paragraph in paragraphs:
        # Preserve internal newlines as ADF hardBreaks.
        para_content: list[dict] = []
        lines = paragraph.split("\n")
        for i, line in enumerate(lines):
            if i > 0:
                para_content.append({"type": "hardBreak"})
            if line:
                para_content.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": para_content})
    return {"type": "doc", "version": 1, "content": content}


def post_jira(dry_run: bool = False) -> None:
    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    summary, description = _parse_jira_md(JIRA_MD.read_text())

    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": ISSUE_TYPE},
            "summary": summary,
            "description": _to_adf(description),
        }
    }

    if dry_run:
        print(f"[dry-run] would POST to {base_url}/rest/api/3/issue")
        print(f"  project:   {project_key}")
        print(f"  issuetype: {ISSUE_TYPE}")
        print(f"  summary:   {summary}")
        print(f"  description ({len(description)} chars):")
        for line in description.splitlines():
            print(f"    {line}")
        return

    resp = requests.post(
        f"{base_url}/rest/api/3/issue",
        json=payload,
        auth=(email, api_token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=15,
    )

    if resp.status_code == 201:
        data = resp.json()
        key = data.get("key")
        print(f"Created Jira issue: {key}")
        print(f"URL: {base_url}/browse/{key}")
        return

    print(f"Failed to create Jira issue: HTTP {resp.status_code}")
    print(resp.text)
    sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Jira issue from jira.md")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without calling Jira")
    args = parser.parse_args()
    post_jira(dry_run=args.dry_run)
