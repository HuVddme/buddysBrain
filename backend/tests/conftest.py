"""Use real FastAPI routes with fake storage/embeddings and no network access."""
import os
import socket
import sys
from threading import Lock
from types import ModuleType
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

database = ModuleType("app.database")
database.collection = Mock()
database.usage_collection = Mock()
database.passage_collection = Mock()
sys.modules["app.database"] = database
embeddings = ModuleType("app.services.embeddings")
embeddings.get_embedding = Mock(return_value=[0.1, 0.2])
embeddings.get_embedding_model = Mock()
embeddings._model_lock = Lock()
sys.modules["app.services.embeddings"] = embeddings

with patch.dict(os.environ, {"FRONTEND_ORIGINS": "http://localhost:5173"}):
    from app.main import app
from app.routes import resources, search


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESOURCE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("DOCUMENT_INGESTION_ENABLED", raising=False)
    for variable in ("OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "OPENAI_MAX_COMPLETION_TOKENS"):
        monkeypatch.delenv(variable, raising=False)
    # Ordinary route tests isolate the quota store. Dedicated usage tests restore
    # the real reservation method and exercise rejection before paid work.
    from app.usage import limiter
    monkeypatch.setattr(limiter, "reserve", AsyncMock())
    class EmptyCursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    passage_store = Mock()
    passage_store.aggregate.return_value = EmptyCursor()
    passage_store.delete_many = AsyncMock()
    passage_store.insert_many = AsyncMock()
    from app.services import passage_store as publication
    from app.routes import passage_admin
    for module in (search, resources, publication, passage_admin):
        monkeypatch.setattr(module, "passage_collection", passage_store)
    from app.services.processing import get_ai_client
    get_ai_client.cache_clear()
    yield
    get_ai_client.cache_clear()


@pytest.fixture
def db(monkeypatch):
    collection = Mock()
    collection.insert_one = AsyncMock()
    collection.insert_many = AsyncMock()
    collection.find_one = AsyncMock()
    collection.delete_one = AsyncMock()
    collection.update_one = AsyncMock()
    collection.replace_one = AsyncMock()
    monkeypatch.setattr(resources, "collection", collection)
    monkeypatch.setattr(search, "collection", collection)
    from app.services import passage_store
    monkeypatch.setattr(passage_store, "collection", collection)
    return collection


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
