"""Inject scenario logs into Google Cloud Logging.

Reads the .jsonl files in logs/ and pushes each service's entries into its
own log under projects/{project}/logs/production%2F{service}.

Timestamps are anchored to (now - 10 minutes) + offset_seconds so the logs
appear as a recent incident. Inject immediately before triggering the Jira alert.

Also updates the Triggered timestamp in jira.md to the current UTC time.

Usage:
    python tests/scenarios/slow_db_queries/inject.py
    python tests/scenarios/slow_db_queries/inject.py --dry-run
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import logging as gcp_logging
from google.cloud.logging import Resource

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ.get("GOOGLE_CLOUD_REGION")
LOG_PREFIX = "production"
LOGS_DIR = Path(__file__).parent / "logs"
JIRA_MD = Path(__file__).parent / "jira.md"

_SEVERITY_MAP = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


def _make_resource(service: str) -> Resource:
    return Resource(
        type="generic_task",
        labels={
            "project_id": PROJECT_ID,
            "location": REGION,
            "namespace": LOG_PREFIX,
            "job": service,
            "task_id": "0",
        },
    )


def inject(dry_run: bool = False) -> None:
    client = gcp_logging.Client(project=PROJECT_ID)

    # Anchor: incident started 10 minutes ago
    anchor_ts = time.time() - 600
    inject_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    for jsonl_file in sorted(LOGS_DIR.glob("*.jsonl")):
        service = jsonl_file.stem  # e.g. "api-service"
        log_name = f"{LOG_PREFIX}/{service}"
        print(f"\nProcessing {service} → projects/{PROJECT_ID}/logs/{log_name} ...")

        entries = []
        with jsonl_file.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                offset = entry.pop("offset_seconds", 0)
                severity = _SEVERITY_MAP.get(entry.pop("level", "INFO"), "INFO")
                ts = datetime.fromtimestamp(anchor_ts + offset, tz=timezone.utc)
                entries.append((ts, severity, entry))

        if dry_run:
            print(f"  [dry-run] would write {len(entries)} entries")
            for ts, severity, payload in entries[:3]:
                print(f"    {ts.isoformat()} [{severity}] {payload.get('message', '')[:80]}")
            if len(entries) > 3:
                print(f"    ... and {len(entries) - 3} more")
            continue

        logger = client.logger(log_name)
        for ts, severity, payload in entries:
            logger.log_struct(
                payload,
                severity=severity,
                timestamp=ts,
                labels={"scenario": "slow_db_queries", "inject_id": inject_id},
                resource=_make_resource(service),
            )
        print(f"  Wrote {len(entries)} entries")

    _update_jira_timestamp(dry_run)

    print("\nDone.")
    if not dry_run:
        print(f"inject_id:  {inject_id}")
        print(f"Console:    https://console.cloud.google.com/logs/query?project={PROJECT_ID}")


def _update_jira_timestamp(dry_run: bool) -> None:
    triggered = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    original = JIRA_MD.read_text()
    updated = re.sub(r"Triggered:.*", f"Triggered: {triggered}", original)
    if dry_run:
        print(f"\n  [dry-run] would update jira.md Triggered: {triggered}")
        return
    JIRA_MD.write_text(updated)
    print(f"\nUpdated jira.md: Triggered: {triggered}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject slow-db-queries scenario into Cloud Logging")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to GCP")
    args = parser.parse_args()
    inject(dry_run=args.dry_run)
