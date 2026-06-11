#!/usr/bin/env bash
# Copyright 2026 Google LLC. Apache-2.0.
#
# Delete all Memory Bank memories under a given (app_name, user_id) scope on
# the deployed Reasoning Engine. Defaults to the partition shared by the Jira
# webhook and chainlit chat: app_name="app", user_id="sre-agent".
#
# Required env vars:
#   GOOGLE_CLOUD_PROJECT    Project hosting the engine.
#   AGENT_RUNTIME_RESOURCE  Engine resource name, e.g.
#                           projects/<num>/locations/us-east1/reasoningEngines/<id>
#
# Optional env vars:
#   SCOPE_APP_NAME   app_name to clear (default: app).
#   SCOPE_USER_ID    user_id to clear  (default: sre-agent).
#   FORCE            Skip the y/N prompt if set (e.g. FORCE=1).

set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
: "${AGENT_RUNTIME_RESOURCE:?set AGENT_RUNTIME_RESOURCE (run 'make deploy' to populate deployment_metadata.json)}"

SCOPE_APP="${SCOPE_APP_NAME:-app}"
SCOPE_USER="${SCOPE_USER_ID:-sre-agent}"
REGION="$(echo "$AGENT_RUNTIME_RESOURCE" | awk -F/ '{print $4}')"
BASE_URL="https://${REGION}-aiplatform.googleapis.com/v1beta1"

TOKEN="$(gcloud auth print-access-token)"

MEMS_JSON="$(curl -sS -X GET \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT}" \
    "${BASE_URL}/${AGENT_RUNTIME_RESOURCE}/memories?pageSize=200")"

NAMES="$(printf '%s' "$MEMS_JSON" | SCOPE_APP="$SCOPE_APP" SCOPE_USER="$SCOPE_USER" python3 -c "
import json, os, sys
data = json.load(sys.stdin)
app = os.environ['SCOPE_APP']
user = os.environ['SCOPE_USER']
for m in data.get('memories', []):
    s = m.get('scope', {})
    if s.get('app_name') == app and s.get('user_id') == user:
        print(m['name'])
")"

if [ -z "$NAMES" ]; then
    echo "No memories under (app_name=${SCOPE_APP}, user_id=${SCOPE_USER}). Nothing to delete."
    exit 0
fi

COUNT="$(printf '%s\n' "$NAMES" | grep -c .)"
echo "Found ${COUNT} memory entries under (app_name=${SCOPE_APP}, user_id=${SCOPE_USER}):"
printf '  %s\n' $NAMES

if [ -z "${FORCE:-}" ]; then
    read -rp "Delete all ${COUNT}? [y/N] " ans
    case "$ans" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0;;
    esac
fi

while IFS= read -r name; do
    [ -z "$name" ] && continue
    echo "→ deleting $name"
    curl -sS -X DELETE \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT}" \
        "${BASE_URL}/${name}" >/dev/null
done <<< "$NAMES"

echo "✓ Cleared ${COUNT} memories."
