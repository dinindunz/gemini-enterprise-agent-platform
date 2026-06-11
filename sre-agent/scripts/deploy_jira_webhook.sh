#!/usr/bin/env bash
# Copyright 2026 Google LLC. Apache-2.0.
#
# Provision the Jira webhook end-to-end:
#   1. Enable required GCP APIs.
#   2. Upsert the Secret Manager secret holding Jira credentials.
#   3. Grant IAM:
#        - Function runtime SA: secretmanager.secretAccessor + aiplatform.user
#        - Agent runtime SA:    secretmanager.secretAccessor
#   4. Deploy the Cloud Function (Gen 2).
#
# Required env vars (set these manually before running):
#   GOOGLE_CLOUD_PROJECT       GCP project ID.
#   AGENT_RUNTIME_RESOURCE     Agent Engine resource name, e.g.
#                              projects/<num>/locations/us-east1/reasoningEngines/<id>
#   JIRA_BASE_URL              e.g. https://yourorg.atlassian.net
#   JIRA_EMAIL                 Jira account email used for API auth.
#   JIRA_API_TOKEN             Jira API token.
#   JIRA_WEBHOOK_SECRET        Shared secret Jira uses to sign webhook payloads.
#
# Optional env vars:
#   JIRA_SECRET_NAME           Secret name (default: jira-webhook).
#   JIRA_WEBHOOK_NAME          Cloud Function name (default: jira-webhook).
#   JIRA_WEBHOOK_REGION        Region (default: us-east1).
#   FUNCTION_RUNTIME_SA        Function runtime SA (default: project's compute SA).

set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
: "${AGENT_RUNTIME_RESOURCE:?set AGENT_RUNTIME_RESOURCE (run 'make deploy' to populate deployment_metadata.json)}"
: "${JIRA_BASE_URL:?set JIRA_BASE_URL}"
: "${JIRA_EMAIL:?set JIRA_EMAIL}"
: "${JIRA_API_TOKEN:?set JIRA_API_TOKEN}"
: "${JIRA_WEBHOOK_SECRET:?set JIRA_WEBHOOK_SECRET}"

JIRA_SECRET_NAME="${JIRA_SECRET_NAME:-jira-webhook}"
JIRA_WEBHOOK_NAME="${JIRA_WEBHOOK_NAME:-jira-webhook}"
JIRA_WEBHOOK_REGION="${JIRA_WEBHOOK_REGION:-us-east1}"

PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"
FUNCTION_RUNTIME_SA="${FUNCTION_RUNTIME_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
AGENT_RUNTIME_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/../functions/jira_webhook"

echo "==> Enabling APIs"
gcloud services enable \
    secretmanager.googleapis.com \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    aiplatform.googleapis.com \
    --project="$GOOGLE_CLOUD_PROJECT"

echo "==> Upserting secret '$JIRA_SECRET_NAME'"
SECRET_PAYLOAD="$(printf '{"base_url":"%s","email":"%s","api_token":"%s","webhook_secret":"%s"}' \
    "$JIRA_BASE_URL" "$JIRA_EMAIL" "$JIRA_API_TOKEN" "$JIRA_WEBHOOK_SECRET")"

if gcloud secrets describe "$JIRA_SECRET_NAME" --project="$GOOGLE_CLOUD_PROJECT" >/dev/null 2>&1; then
    printf '%s' "$SECRET_PAYLOAD" | gcloud secrets versions add "$JIRA_SECRET_NAME" \
        --data-file=- --project="$GOOGLE_CLOUD_PROJECT"
else
    printf '%s' "$SECRET_PAYLOAD" | gcloud secrets create "$JIRA_SECRET_NAME" \
        --data-file=- --replication-policy=automatic --project="$GOOGLE_CLOUD_PROJECT"
fi

echo "==> Granting secret accessor to function SA ($FUNCTION_RUNTIME_SA)"
gcloud secrets add-iam-policy-binding "$JIRA_SECRET_NAME" \
    --member="serviceAccount:${FUNCTION_RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$GOOGLE_CLOUD_PROJECT" --quiet >/dev/null

echo "==> Granting secret accessor to agent runtime SA ($AGENT_RUNTIME_SA)"
gcloud secrets add-iam-policy-binding "$JIRA_SECRET_NAME" \
    --member="serviceAccount:${AGENT_RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$GOOGLE_CLOUD_PROJECT" --quiet >/dev/null

echo "==> Granting aiplatform.user to function SA"
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
    --member="serviceAccount:${FUNCTION_RUNTIME_SA}" \
    --role="roles/aiplatform.user" \
    --condition=None --quiet >/dev/null

echo "==> Deploying Cloud Function '$JIRA_WEBHOOK_NAME' in $JIRA_WEBHOOK_REGION"
gcloud functions deploy "$JIRA_WEBHOOK_NAME" \
    --gen2 \
    --region="$JIRA_WEBHOOK_REGION" \
    --runtime=python312 \
    --source="$SOURCE_DIR" \
    --entry-point=handler \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$FUNCTION_RUNTIME_SA" \
    --timeout=540 \
    --memory=512Mi \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},AGENT_RUNTIME_RESOURCE=${AGENT_RUNTIME_RESOURCE},JIRA_SECRET_NAME=${JIRA_SECRET_NAME}" \
    --project="$GOOGLE_CLOUD_PROJECT"

echo
echo "✓ Done. Webhook URL:"
gcloud functions describe "$JIRA_WEBHOOK_NAME" \
    --gen2 --region="$JIRA_WEBHOOK_REGION" \
    --project="$GOOGLE_CLOUD_PROJECT" \
    --format='value(serviceConfig.uri)'
