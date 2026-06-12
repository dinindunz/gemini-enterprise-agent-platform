# BigQuery Agent Analytics — CLI Queries

Inspect the SRE agent's inference logs (sunk to BigQuery by `make telemetry-bq`)
from the terminal. All snippets read `GOOGLE_CLOUD_PROJECT` from `sre-agent/.env`,
so they work without hard-coding the project.

Run any of these from the `sre-agent/` directory.

## 0. Load the project from `.env`

Do this once per shell session:

```bash
set -a; source .env; set +a
```

`GOOGLE_CLOUD_PROJECT` is now exported for use by `bq`.

## 1. Recent inference events

Each row = one LLM call (or tool call) made by the agent. Includes agent name,
user, invocation/event IDs, token usage, and the trace link back to Cloud Trace.

```bash
bq query --use_legacy_sql=false --project_id=$GOOGLE_CLOUD_PROJECT '
SELECT
  timestamp,
  labels.gen_ai_agent_name                  AS agent,
  labels.user_id                            AS user_id,
  labels.gcp_vertex_agent_invocation_id     AS invocation_id,
  labels.gcp_vertex_agent_event_id          AS event_id,
  labels.gen_ai_conversation_id             AS conversation_id,
  CAST(labels.gen_ai_usage_input_tokens  AS INT64) AS input_tokens,
  CAST(labels.gen_ai_usage_output_tokens AS INT64) AS output_tokens,
  trace,
  spanId
FROM `'$GOOGLE_CLOUD_PROJECT'.sre_agent_analytics.gen_ai_client_inference_operation_details_*`
ORDER BY timestamp DESC
LIMIT 50'
```

## 2. Token spend by agent and day

Daily roll-up for cost tracking.

```bash
bq query --use_legacy_sql=false --project_id=$GOOGLE_CLOUD_PROJECT '
SELECT
  DATE(timestamp)            AS day,
  labels.gen_ai_agent_name   AS agent,
  COUNT(*)                   AS events,
  SUM(CAST(labels.gen_ai_usage_input_tokens  AS INT64)) AS input_tokens,
  SUM(CAST(labels.gen_ai_usage_output_tokens AS INT64)) AS output_tokens
FROM `'$GOOGLE_CLOUD_PROJECT'.sre_agent_analytics.gen_ai_client_inference_operation_details_*`
GROUP BY day, agent
ORDER BY day DESC, agent'
```

## 3. All events for a single invocation

Set `INVOCATION_ID` to a value from query (1) above (the `invocation_id` column)
or from the trace UI — handy for following one Jira ticket through the agent.

```bash
INVOCATION_ID=e-fa9fa1db-3318-43b3-b5ce-91eef641dc42  # replace with yours

bq query --use_legacy_sql=false --project_id=$GOOGLE_CLOUD_PROJECT \
  --parameter=invocation_id:STRING:$INVOCATION_ID '
SELECT
  timestamp,
  labels.gcp_vertex_agent_event_id  AS event_id,
  CAST(labels.gen_ai_usage_input_tokens  AS INT64) AS input_tokens,
  CAST(labels.gen_ai_usage_output_tokens AS INT64) AS output_tokens,
  trace
FROM `'$GOOGLE_CLOUD_PROJECT'.sre_agent_analytics.gen_ai_client_inference_operation_details_*`
WHERE labels.gcp_vertex_agent_invocation_id = @invocation_id
ORDER BY timestamp'
```

## Jumping from BQ row to Cloud Trace

Every row has a `trace` column shaped like
`projects/<project>/traces/<trace_id>`. To open it in the console:

```bash
TRACE_ID=$(echo "<trace value from BQ>" | awk -F/ '{print $NF}')
open "https://console.cloud.google.com/traces/list?project=$GOOGLE_CLOUD_PROJECT&tid=$TRACE_ID"
```
