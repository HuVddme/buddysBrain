import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock
import tomllib
import json

from fastapi.testclient import TestClient

from app.routes import search, resources
from vercel_app import app


def test_mount_preserves_api_prefix_and_docs():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/health").status_code == 404
        schema = client.get("/api/openapi.json").json()
        assert schema["servers"] == [{"url": "/api"}]
        assert "/search" in schema["paths"]
        assert client.get("/api/docs").status_code == 200


def test_prefixed_search_calls_existing_handler(db, monkeypatch):
    class Cursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    db.aggregate.return_value = Cursor()
    summarize = Mock(return_value="Live answer")
    monkeypatch.setattr(search, "summarize_resources", summarize)
    with TestClient(app) as client:
        response = client.post("/api/search", json={"query": "Explain limits"})
    assert response.status_code == 200
    assert response.json() == {"summary": "Live answer", "results": []}
    summarize.assert_called_once_with([], "Explain limits")


def test_prefixed_deletion_still_requires_admin(db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    with TestClient(app) as client:
        response = client.delete("/api/resources/507f1f77bcf86cd799439011")
    assert response.status_code == 401
    db.delete_one.assert_not_called()


def test_vercel_file_limit_rejects_before_processing(db, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    process = Mock()
    monkeypatch.setattr(resources, "process_upload", process)
    with TestClient(app) as client:
        response = client.post("/api/upload", data={"title": "T", "description": "D", "course": "CS"},
                               files={"file": ("notes.txt", b"a" * 4_000_001)})
    assert response.status_code == 413
    assert "4 MB" in response.json()["detail"]
    process.assert_not_called()
    db.insert_one.assert_not_called()


def test_uv_and_pip_dependency_lists_match():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    pip_deps = {line for name in ("requirements.txt", "requirements-api.txt")
                for line in (root / name).read_text().splitlines()
                if line and not line.startswith(("-r", "#"))}
    assert set(config["project"]["dependencies"]) == pip_deps


def test_services_build_declares_both_api_and_queue_worker():
    root = Path(__file__).resolve().parents[1]
    services = json.loads((root.parent / 'vercel.json').read_text())['services']
    config = tomllib.loads((root / 'pyproject.toml').read_text())['tool']['vercel']
    # Direct Python entrypoints in Services silently exclude subscriber declarations.
    assert services['api']['entrypoint'] == 'pyproject.toml'
    assert config['entrypoint'] == 'vercel_app:app'
    assert config['subscribers'] == [{'entrypoint': 'app.ingestion_subscriber'}]


def test_embedding_load_is_lazy_reused_and_keeps_existing_model(monkeypatch):
    # Read the actual embedding module in isolation: ordinary route tests stub it.
    path = Path(__file__).resolve().parents[1] / "app/services/embeddings.py"
    fake = ModuleType("sentence_transformers")
    factory = Mock()
    factory.return_value.encode.return_value.tolist.return_value = [0.1, 0.2]
    fake.SentenceTransformer = factory
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setenv("VERCEL", "1")
    spec = importlib.util.spec_from_file_location("embedding_test_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory.assert_not_called()
    assert module.get_embedding("") == []
    factory.assert_not_called()
    assert module.get_embedding("first") == [0.1, 0.2]
    assert module.get_embedding("second") == [0.1, 0.2]
    assert factory.call_count == 1
    assert factory.call_args.args == ("all-MiniLM-L6-v2",)
    assert Path(factory.call_args.kwargs["cache_folder"]).name == "buddysbrain-models"
