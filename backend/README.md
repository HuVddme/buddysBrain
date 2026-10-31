# Buddy's Brain API

FastAPI handles search and resource uploads. MongoDB stores resources and vectors;
Cloudinary stores uploads; OpenAI generates summaries and answers.

From this directory, use Python 3.12:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Fill `.env` privately with your own credentials before starting the server.
The host environment takes precedence over local values. Never commit `.env`.
For tests without model downloads or credentials, install `requirements-test.txt`
instead and run `python -m pytest -q`.

- `app/routes/`: HTTP endpoints and database operations.
- `app/services/`: reusable ingestion, AI, embedding and storage logic.
- `app/utils/`: URL safety and MongoDB serialization helpers.
- `vercel_app.py`: mounts the API at `/api` for the root Vercel Services deployment.
- `pyproject.toml`: deployment dependencies, including Linux CPU-only PyTorch.
- `requirements*.txt`: pip-based local and isolated-test installation.

The standalone API exposes `/health`, `/docs`, `/search` and resource endpoints.
On the combined Vercel deployment these are prefixed with `/api`.
Health checks liveness only; it does not verify the database or providers.

For document passage search, follow the [index setup and reprocessing guide](../docs/passage-retrieval.md).
The authenticated `scripts/passage_admin.py` helper calls the deployed backend;
it does not require the embedding model or database credentials on your laptop.

See the [root setup instructions](../README.md) and
[architecture](../docs/architecture.md) for deployment settings, limits and
features still to be implemented.
