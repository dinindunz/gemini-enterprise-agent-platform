#!/usr/bin/env bash
# Copyright 2026 Google LLC. Apache-2.0.
#
# Grant the IAM roles needed for the Cloud Logging MCP server.
#
# - Both the developer (ADC) and the deployed agent runtime SA get:
#     * roles/logging.viewer       — read the underlying Cloud Logging entries
#     * roles/agentregistry.viewer — list/get registered MCP servers
#     * roles/mcp.toolUser         — INVOKE tools on managed MCP servers
#       (grants mcp.tools.call; without this the handshake succeeds but every
#       tool-call message returns 403 at the MCP gateway). See:
#       https://docs.cloud.google.com/logging/docs/use-logging-mcp
#       https://docs.cloud.google.com/mcp/control-mcp-use-iam
#
# Required env vars:
#   GOOGLE_CLOUD_PROJECT  Target project.
#   GCLOUD_USER           Developer account email.
#   MCP_RUNTIME_SA        Agent runtime service account email.

set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
: "${GCLOUD_USER:?set GCLOUD_USER (e.g. \$(gcloud config get-value account))}"
: "${MCP_RUNTIME_SA:?set MCP_RUNTIME_SA}"

SHARED_ROLES=(roles/logging.viewer roles/agentregistry.viewer roles/mcp.toolUser)
SA_ONLY_ROLES=()

grant() {
    local member="$1" role="$2"
    echo "→ Granting $role to $member"
    gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
        --member="$member" --role="$role" \
        --condition=None --quiet >/dev/null
}

for role in "${SHARED_ROLES[@]}"; do
    grant "user:${GCLOUD_USER}" "$role"
    grant "serviceAccount:${MCP_RUNTIME_SA}" "$role"
done

for role in ${SA_ONLY_ROLES[@]+"${SA_ONLY_ROLES[@]}"}; do
    grant "serviceAccount:${MCP_RUNTIME_SA}" "$role"
done

echo "✓ MCP grants applied."

# Optional cleanup: if you previously ran an older version of this script that
# granted roles/aiplatform.user to the SA as a speculative MCP fix, you can
# remove it — it wasn't the missing piece:
#   gcloud projects remove-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
#     --member="serviceAccount:${MCP_RUNTIME_SA}" --role="roles/aiplatform.user"
