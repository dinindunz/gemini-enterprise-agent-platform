DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

include $(DIR).env
export

SCENARIO ?= slow_db_queries
AGENT_ENGINE_ID := $(shell python3 -c "import json; print(open('$(DIR)deployment_metadata.json').read())" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['remote_agent_runtime_id'].split('/')[-1])" 2>/dev/null)

.PHONY: chat dev deploy inject cleanup mcp-setup mcp-enable mcp-grant mcp-list deploy-webhook clear-memory telemetry-setup telemetry-bucket telemetry-bq

# ---- MCP setup (Google Cloud Observability MCP server) -------------------
# Registers Cloud Logging as a remote MCP server and grants the IAM needed
# for both the developer (ADC) and the deployed agent's runtime SA.
# Targets are idempotent.
LOGGING_MCP        := logging.googleapis.com
GCLOUD_USER        := $(shell gcloud config get-value account 2>/dev/null)
PROJECT_NUMBER     := $(shell gcloud projects describe $(GOOGLE_CLOUD_PROJECT) --format='value(projectNumber)' 2>/dev/null)
# Vertex AI Agent Engine default runtime SA. Override MCP_RUNTIME_SA in .env
# if you deploy with a custom service account.
MCP_RUNTIME_SA     ?= service-$(PROJECT_NUMBER)@gcp-sa-aiplatform-re.iam.gserviceaccount.com

mcp-setup: mcp-enable mcp-grant
	@echo "✓ MCP setup complete. Run 'make mcp-list' to verify."

mcp-enable:
	gcloud services enable $(LOGGING_MCP) agentregistry.googleapis.com \
		--project=$(GOOGLE_CLOUD_PROJECT)

mcp-grant:
	@GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
	GCLOUD_USER=$(GCLOUD_USER) \
	MCP_RUNTIME_SA=$(MCP_RUNTIME_SA) \
	bash $(DIR)scripts/mcp_grant.sh

mcp-list:
	gcloud alpha agent-registry mcp-servers list \
		--project=$(GOOGLE_CLOUD_PROJECT) \
		--location=global

inject:
	cd $(DIR) && uv run python tests/scenarios/$(SCENARIO)/inject.py

cleanup:
	cd $(DIR) && uv run python tests/scenarios/$(SCENARIO)/cleanup.py

dev:
	@echo "ADK web UI with Memory Bank: http://localhost:8000"
	cd $(DIR) && uv run adk web --memory_service_uri=agentengine://$(AGENT_ENGINE_ID)

chat:
	@echo "Chat UI running at http://localhost:8001"
	cd $(DIR) && uv run chainlit run app/chainlit_app.py -w --port 8001

deploy:
	cd $(DIR) && agents-cli deploy \
		--project $(GOOGLE_CLOUD_PROJECT) \
		--region $(GOOGLE_CLOUD_REGION) \
		--no-confirm-project

# ---- Jira webhook Cloud Function -----------------------------------------
# Provisions secret + IAM + deploys the function. Expects these env vars to be
# set in the shell before running (NOT committed to .env):
#   JIRA_BASE_URL JIRA_EMAIL JIRA_API_TOKEN JIRA_WEBHOOK_SECRET
# Re-running is safe — the script upserts the secret and IAM bindings.
AGENT_RUNTIME_RESOURCE := $(shell python3 -c "import json; print(json.load(open('$(DIR)deployment_metadata.json'))['remote_agent_runtime_id'])" 2>/dev/null)

deploy-webhook:
	@test -n "$(AGENT_RUNTIME_RESOURCE)" || (echo "AGENT_RUNTIME_RESOURCE empty — run 'make deploy' first"; exit 1)
	AGENT_RUNTIME_RESOURCE=$(AGENT_RUNTIME_RESOURCE) \
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
	JIRA_SECRET_NAME=$(JIRA_SECRET_NAME) \
	JIRA_WEBHOOK_REGION=$(GOOGLE_CLOUD_REGION) \
	bash $(DIR)scripts/deploy_jira_webhook.sh

# ---- Observability: prompt-response logging + BQ analytics ---------------
# telemetry-bucket: GCS bucket for completions (NDJSON) + IAM for runtime SA.
# telemetry-bq:     BQ dataset + Cloud Logging sink for inference logs.
# telemetry-setup:  both. Re-runnable; safe to call before or after `make deploy`
#                   (BQ sink auto-narrows to the deployed engine ID when present).
LOGS_BUCKET_NAME ?= $(GOOGLE_CLOUD_PROJECT)-sre-agent-logs
BQ_DATASET       ?= sre_agent_analytics

telemetry-bucket:
	@GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
	GOOGLE_CLOUD_REGION=$(GOOGLE_CLOUD_REGION) \
	LOGS_BUCKET_NAME=$(LOGS_BUCKET_NAME) \
	MCP_RUNTIME_SA=$(MCP_RUNTIME_SA) \
	bash $(DIR)scripts/setup_telemetry_bucket.sh
	@echo "✓ Telemetry setup complete. Add LOGS_BUCKET_NAME=$(LOGS_BUCKET_NAME) to .env, then 'make deploy'."

telemetry-bq:
	@GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
	BQ_DATASET=$(BQ_DATASET) \
	AGENT_RUNTIME_RESOURCE="$(AGENT_RUNTIME_RESOURCE)" \
	bash $(DIR)scripts/setup_bq_analytics.sh

# Delete all Memory Bank entries under the shared SRE partition
# (app_name=app, user_id=sre-agent). Override SCOPE_APP_NAME / SCOPE_USER_ID
# to target a different scope; pass FORCE=1 to skip the y/N prompt.
clear-memory:
	@test -n "$(AGENT_RUNTIME_RESOURCE)" || (echo "AGENT_RUNTIME_RESOURCE empty — run 'make deploy' first"; exit 1)
	@AGENT_RUNTIME_RESOURCE=$(AGENT_RUNTIME_RESOURCE) \
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
	bash $(DIR)scripts/clear_memory.sh
