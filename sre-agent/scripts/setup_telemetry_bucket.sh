#!/usr/bin/env bash
# Copyright 2026 Google LLC. Apache-2.0.
#
# Provision the GCS bucket that holds prompt-response completions (JSONL).
#
# Steps (idempotent):
#   1. Create gs://${LOGS_BUCKET_NAME} in ${GOOGLE_CLOUD_REGION}.
#   2. Grant the agent runtime SA roles/storage.objectCreator + objectViewer
#      so it can write completions and read them back (for the completions view).
#
# Required env vars:
#   GOOGLE_CLOUD_PROJECT  Target project.
#   GOOGLE_CLOUD_REGION   Bucket location (default: us-east1).
#
# Optional env vars:
#   LOGS_BUCKET_NAME      Bucket short name (default: ${GOOGLE_CLOUD_PROJECT}-sre-agent-logs).
#   MCP_RUNTIME_SA        Runtime SA (default: project's Agent Engine SA).

set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"

GOOGLE_CLOUD_REGION="${GOOGLE_CLOUD_REGION:-us-east1}"
LOGS_BUCKET_NAME="${LOGS_BUCKET_NAME:-${GOOGLE_CLOUD_PROJECT}-sre-agent-logs}"

PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"
MCP_RUNTIME_SA="${MCP_RUNTIME_SA:-service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com}"

echo "==> Enabling APIs"
gcloud services enable storage.googleapis.com \
    --project="$GOOGLE_CLOUD_PROJECT" --quiet >/dev/null

echo "==> Creating bucket gs://${LOGS_BUCKET_NAME} (${GOOGLE_CLOUD_REGION})"
if gcloud storage buckets describe "gs://${LOGS_BUCKET_NAME}" \
    --project="$GOOGLE_CLOUD_PROJECT" >/dev/null 2>&1; then
    echo "    Already exists, skipping create"
else
    gcloud storage buckets create "gs://${LOGS_BUCKET_NAME}" \
        --project="$GOOGLE_CLOUD_PROJECT" \
        --location="$GOOGLE_CLOUD_REGION" \
        --uniform-bucket-level-access
fi

echo "==> Granting agent runtime SA (${MCP_RUNTIME_SA}) read+write on bucket"
for role in roles/storage.objectCreator roles/storage.objectViewer; do
    gcloud storage buckets add-iam-policy-binding "gs://${LOGS_BUCKET_NAME}" \
        --member="serviceAccount:${MCP_RUNTIME_SA}" \
        --role="$role" --quiet >/dev/null
    echo "    Granted $role"
done

echo
echo "✓ Bucket ready."
echo
echo "Next: add this line to sre-agent/.env, then run 'make deploy':"
echo
echo "    LOGS_BUCKET_NAME=${LOGS_BUCKET_NAME}"
echo
