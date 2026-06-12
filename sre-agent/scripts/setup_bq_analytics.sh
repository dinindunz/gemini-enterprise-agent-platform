#!/usr/bin/env bash
# Copyright 2026 Google LLC. Apache-2.0.
#
# Provision BigQuery Agent Analytics for the SRE agent:
#   1. Create the BQ dataset.
#   2. Create a Cloud Logging sink that ships GenAI inference logs
#      (resource.type = aiplatform.googleapis.com/ReasoningEngine) to BQ.
#      If deployment_metadata.json exists, the sink is scoped to that engine ID
#      only; otherwise it matches any Reasoning Engine in the project.
#   3. Grant the sink's writer service account roles/bigquery.dataEditor on the
#      dataset so it can land logs.
#
# Required env vars:
#   GOOGLE_CLOUD_PROJECT  Target project.
#
# Optional env vars:
#   BQ_DATASET            Dataset name (default: sre_agent_analytics).
#   BQ_LOCATION           Dataset location (default: US).
#   LOG_SINK_NAME         Sink name (default: sre-agent-analytics).
#   AGENT_RUNTIME_RESOURCE
#                         Full reasoning engine resource name. If unset, the
#                         script reads sre-agent/deployment_metadata.json.

set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"

BQ_DATASET="${BQ_DATASET:-sre_agent_analytics}"
BQ_LOCATION="${BQ_LOCATION:-US}"
LOG_SINK_NAME="${LOG_SINK_NAME:-sre-agent-analytics}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META="${SCRIPT_DIR}/../deployment_metadata.json"

if [[ -z "${AGENT_RUNTIME_RESOURCE:-}" && -f "$META" ]]; then
    AGENT_RUNTIME_RESOURCE="$(python3 -c "import json; print(json.load(open('$META'))['remote_agent_runtime_id'])" 2>/dev/null || true)"
fi

if [[ -n "${AGENT_RUNTIME_RESOURCE:-}" ]]; then
    ENGINE_ID="${AGENT_RUNTIME_RESOURCE##*/}"
    SINK_FILTER="resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" AND resource.labels.reasoning_engine_id=\"${ENGINE_ID}\""
    echo "==> Sink scoped to engine ${ENGINE_ID}"
else
    SINK_FILTER='resource.type="aiplatform.googleapis.com/ReasoningEngine"'
    echo "==> No deployment_metadata.json — sink will match ALL Reasoning Engines in the project"
fi

echo "==> Enabling APIs"
gcloud services enable bigquery.googleapis.com logging.googleapis.com \
    --project="$GOOGLE_CLOUD_PROJECT" --quiet >/dev/null

echo "==> Creating BigQuery dataset ${GOOGLE_CLOUD_PROJECT}:${BQ_DATASET} (${BQ_LOCATION})"
if bq --project_id="$GOOGLE_CLOUD_PROJECT" show "$BQ_DATASET" >/dev/null 2>&1; then
    echo "    Already exists, skipping create"
else
    bq --project_id="$GOOGLE_CLOUD_PROJECT" mk \
        --location="$BQ_LOCATION" \
        --description="SRE agent inference logs (sink destination)" \
        "$BQ_DATASET"
fi

DESTINATION="bigquery.googleapis.com/projects/${GOOGLE_CLOUD_PROJECT}/datasets/${BQ_DATASET}"

echo "==> Upserting log sink '${LOG_SINK_NAME}'"
if gcloud logging sinks describe "$LOG_SINK_NAME" \
    --project="$GOOGLE_CLOUD_PROJECT" >/dev/null 2>&1; then
    gcloud logging sinks update "$LOG_SINK_NAME" "$DESTINATION" \
        --log-filter="$SINK_FILTER" \
        --project="$GOOGLE_CLOUD_PROJECT" --quiet >/dev/null
    echo "    Sink updated"
else
    gcloud logging sinks create "$LOG_SINK_NAME" "$DESTINATION" \
        --log-filter="$SINK_FILTER" \
        --project="$GOOGLE_CLOUD_PROJECT" >/dev/null
    echo "    Sink created"
fi

WRITER=$(gcloud logging sinks describe "$LOG_SINK_NAME" \
    --project="$GOOGLE_CLOUD_PROJECT" --format='value(writerIdentity)')
echo "    Writer identity: $WRITER"

echo "==> Granting writer roles/bigquery.dataEditor on ${BQ_DATASET}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
bq --project_id="$GOOGLE_CLOUD_PROJECT" show --format=prettyjson "$BQ_DATASET" > "$TMP"
python3 - "$TMP" "${WRITER#serviceAccount:}" <<'PY'
import json, sys
path, member = sys.argv[1], sys.argv[2]
with open(path) as f:
    d = json.load(f)
access = d.setdefault("access", [])
if not any(a.get("role") == "WRITER" and a.get("userByEmail") == member for a in access):
    access.append({"role": "WRITER", "userByEmail": member})
with open(path, "w") as f:
    json.dump(d, f)
PY
bq update --source "$TMP" "$BQ_DATASET" >/dev/null
echo "    Granted"

echo
echo "✓ BigQuery Agent Analytics ready."
echo
echo "Query inference logs once traffic flows (may take a few minutes):"
echo "  bq query --use_legacy_sql=false \\"
echo "    'SELECT timestamp, jsonPayload FROM \`${GOOGLE_CLOUD_PROJECT}.${BQ_DATASET}.*\` ORDER BY timestamp DESC LIMIT 20'"
echo
