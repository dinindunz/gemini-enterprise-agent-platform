DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: chat

chat:
	@echo "Chat UI running at http://localhost:8001"
	cd $(DIR) && uv run chainlit run app/chainlit_app.py -w --port 8001
