"""Delete Cloud Logging entries created by inject.py.

Deletes all entries under production/{service} log names for every
service in the logs/ directory.

Usage:
    python tests/scenarios/slow_db_queries/cleanup.py
    python tests/scenarios/slow_db_queries/cleanup.py --dry-run
"""

import argparse
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import logging as gcp_logging

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOG_PREFIX = "production"
LOGS_DIR = Path(__file__).parent / "logs"


def cleanup(dry_run: bool = False) -> None:
    client = gcp_logging.Client(project=PROJECT_ID)

    services = [f.stem for f in sorted(LOGS_DIR.glob("*.jsonl"))]
    if not services:
        print("No service log files found.")
        return

    deleted = 0
    skipped = 0
    for service in services:
        log_name = quote(f"{LOG_PREFIX}/{service}", safe="")
        if dry_run:
            print(f"[dry-run] would delete: projects/{PROJECT_ID}/logs/{log_name}")
            deleted += 1
            continue
        try:
            client.logger(log_name).delete()
            print(f"Deleted: projects/{PROJECT_ID}/logs/{log_name}")
            deleted += 1
        except NotFound:
            print(f"Skipped (not present): projects/{PROJECT_ID}/logs/{log_name}")
            skipped += 1

    summary = f"\n{'Would delete' if dry_run else 'Deleted'} {deleted} log(s)."
    if skipped:
        summary += f" Skipped {skipped} not present."
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete injected slow-db-queries logs from Cloud Logging")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without deleting from GCP")
    args = parser.parse_args()
    cleanup(dry_run=args.dry_run)
