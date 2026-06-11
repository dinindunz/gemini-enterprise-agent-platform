DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

include $(DIR).env
export

SCENARIO ?= slow_db_queries
AGENT_ENGINE_ID := $(shell python3 -c "import json; print(open('$(DIR)deployment_metadata.json').read())" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['remote_agent_runtime_id'].split('/')[-1])" 2>/dev/null)

.PHONY: chat dev deploy inject cleanup

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
