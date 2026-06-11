DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

include $(DIR).env
export

SCENARIO ?= slow_db_queries
AGENT_ENGINE_ID := $(shell python3 -c "import json; print(open('$(DIR)deployment_metadata.json').read())" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['remote_agent_runtime_id'].split('/')[-1])" 2>/dev/null)

.PHONY: chat dev deploy inject cleanup mcp-setup mcp-enable mcp-grant mcp-list

# ---- MCP setup (Google Cloud Observability MCP server) -------------------
# Registers Cloud Logging as a remote MCP server and grants the IAM needed
# for both the developer (ADC) and the deployed agent's runtime SA.
# Targets are idempotent.
LOGGING_MCP        := logging.googleapis.com
MCP_ROLES          := roles/logging.viewer roles/agentregistry.viewer
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
	@for role in $(MCP_ROLES); do \
		echo "→ Granting $$role to user:$(GCLOUD_USER)"; \
		gcloud projects add-iam-policy-binding $(GOOGLE_CLOUD_PROJECT) \
			--member="user:$(GCLOUD_USER)" --role="$$role" \
			--condition=None --quiet >/dev/null; \
		echo "→ Granting $$role to serviceAccount:$(MCP_RUNTIME_SA)"; \
		gcloud projects add-iam-policy-binding $(GOOGLE_CLOUD_PROJECT) \
			--member="serviceAccount:$(MCP_RUNTIME_SA)" --role="$$role" \
			--condition=None --quiet >/dev/null; \
	done

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
