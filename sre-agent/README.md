# sre-agent


## Project Structure


## Quick Start

**1. Install uv** (if not already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Install Google Cloud SDK** (if not already installed): [Install guide](https://cloud.google.com/sdk/docs/install)

**3. Install agents-cli and its skills:**

```bash
uv tool install google-agents-cli
agents-cli setup
```

**4. Create the virtual environment and install dependencies:**

```bash
uv sync
source .venv/bin/activate
```

**5. Set up your environment:**

```bash
cp .env.example .env
# Edit .env and set GOOGLE_CLOUD_PROJECT to your GCP project ID
```

**6. Authenticate with GCP:**

```bash
gcloud auth login                        # used by `make mcp-setup` for IAM grants
gcloud auth application-default login    # used by the agent to call GCP APIs
```

**7. Set up the Cloud Logging MCP server:**

The agent reads logs via Google's managed Cloud Logging MCP server.
`make mcp-setup` enables the required APIs (`logging.googleapis.com`,
`agentregistry.googleapis.com`) and grants `roles/logging.viewer` +
`roles/agentregistry.viewer` to both your user and the deployed runtime
service account.

```bash
make mcp-setup
make mcp-list    # verify the registry lists logging.googleapis.com
```

> **Fresh-project bootstrap.** If this is a new GCP project that has never
> been used with Vertex AI, run these once before `make mcp-setup`:
>
> ```bash
> # Billing must be linked to the project (UI or `gcloud billing`).
> # Materialize the Vertex AI Agent Engine service identity so IAM grants stick:
> gcloud beta services identity create \
>     --service=aiplatform.googleapis.com \
>     --project=$GOOGLE_CLOUD_PROJECT
> # `make mcp-list` uses the alpha component:
> gcloud components install alpha
> ```
>
> If `mcp-list` returns nothing right after `mcp-setup`, registry provisioning
> is still in flight — wait ~1 minute and retry.
>
> If you deploy with a **custom service account**, set `MCP_RUNTIME_SA` in
> `.env` before running `make mcp-setup`.

**8. Provision the telemetry GCS bucket:**

Creates `gs://${PROJECT}-sre-agent-logs` and grants the runtime SA read/write
on it. Must run **before** `make deploy` so the bucket exists and the IAM is
in place when the agent first writes prompt-response completions.

```bash
make telemetry-bucket
```

Then add the bucket name to `.env` so the deploy bakes it onto the runtime:

```bash
echo "LOGS_BUCKET_NAME=${PROJECT}-sre-agent-logs" >> .env
```

Without this env var, `app/app_utils/telemetry.py` leaves prompt-response
capture disabled and only span-level metadata reaches Cloud Trace.

**9. Deploy the agent to GCP:**

```bash
make deploy
```

This creates the Vertex AI Reasoning Engine and writes `deployment_metadata.json`,
which the next two steps depend on.

**10. Wire up BigQuery Agent Analytics:**

Creates the BQ dataset `sre_agent_analytics` and a Cloud Logging sink scoped
to the engine just deployed. Run **after** `make deploy` so the sink filter
narrows to the deployed engine ID.

```bash
make telemetry-bq
```

Query inference logs once traffic flows (may take a few minutes to propagate):

```bash
bq query --use_legacy_sql=false \
  'SELECT timestamp, jsonPayload FROM `'"$GOOGLE_CLOUD_PROJECT"'.sre_agent_analytics.*` ORDER BY timestamp DESC LIMIT 20'
```

**11. Deploy the Jira webhook:**

Generate a Jira API token: go to `id.atlassian.net → Account Settings → Security → API tokens → Create API token`.

Generate a webhook shared secret:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Export the four `JIRA_*` values in your shell (do NOT commit them to `.env`), then:

```bash
make deploy-webhook
```

In Jira: **Settings → System → Webhooks → Create a Webhook** — set the URL from `deploy-webhook` output, the shared secret, and select the **Issue: created** event for the agent to handle.

**12. Launch the chat UI:**

```bash
make chat
```

## Scenario Testing

Inject synthetic logs into Cloud Logging to simulate an incident, then test the agent against them.

**1. Inject logs:**

```bash
make inject                         # injects the slow_db_queries scenario (default)
make inject SCENARIO=slow_db_queries  # explicit scenario name
```

**2. Run the agent:**

```bash
make chat
```

**3. Clean up injected logs:**

```bash
make cleanup
make cleanup SCENARIO=slow_db_queries  # explicit scenario name
```

**4. Clear Memory Bank (optional):**

The agent accumulates facts across runs in Vertex AI Memory Bank under the
shared SRE partition (`app_name=app`, `user_id=sre-agent`). Stale or incorrect
memories can confuse future investigations — for example, a fact saved during
an earlier misconfiguration (e.g. *"Cloud Logging is unavailable"*) may keep
resurfacing. To wipe the partition:

```bash
make clear-memory             # prompts for y/N
make clear-memory FORCE=1     # skip prompt
```

The same memories appear under **Vertex AI → Agent Engine → your engine → Memory Bank**
in the GCP console; this just removes them via the REST API.

Use `--dry-run` to preview actions without writing to GCP:

```bash
uv run python tests/scenarios/slow_db_queries/inject.py --dry-run
uv run python tests/scenarios/slow_db_queries/cleanup.py --dry-run
```
