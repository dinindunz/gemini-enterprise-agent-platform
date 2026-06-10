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
gcloud auth application-default login
```

**7. Test the agent locally:**

```bash
agents-cli playground
```

**8. Deploy to GCP:**

```bash
make deploy
```

**9. Launch the chat UI:**

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

Use `--dry-run` to preview actions without writing to GCP:

```bash
uv run python tests/scenarios/slow_db_queries/inject.py --dry-run
uv run python tests/scenarios/slow_db_queries/cleanup.py --dry-run
```
