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
