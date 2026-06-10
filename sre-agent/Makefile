DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

include $(DIR).env
export

SCENARIO ?= slow_db_queries

.PHONY: chat deploy inject cleanup

inject:
	cd $(DIR) && uv run python tests/scenarios/$(SCENARIO)/inject.py

cleanup:
	cd $(DIR) && uv run python tests/scenarios/$(SCENARIO)/cleanup.py

chat:
	@echo "Chat UI running at http://localhost:8001"
	cd $(DIR) && uv run chainlit run app/chainlit_app.py -w --port 8001

deploy:
	cd $(DIR) && agents-cli deploy \
		--project $(GOOGLE_CLOUD_PROJECT) \
		--region $(GOOGLE_CLOUD_REGION) \
		--no-confirm-project
