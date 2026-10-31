import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import pytest

from app.routes import resources, search
from app.usage import UsageLimiter, limiter


NOW = datetime(2026, 10, 28, 12, 0, 30, tzinfo=timezone.utc)


class AtomicCounterStore:
    """In-memory Mongo test double for the exact conditional update contract.

    Production Mongo concurrency and TTL cleanup still need an integration check.
    """
    def __init__(self):
        self.documents = {}
        self.lock = asyncio.Lock()
        self.create_index = AsyncMock()

    async def find_one_and_update(self, query, update, *, upsert, return_document):
        assert return_document is True
        async with self.lock:
            key = query["_id"]
            count = self.documents.get(key, {}).get("count")
            maximum = query["count"]["$lte"]
            if count is not None and count > maximum:
                if upsert:
                    raise DuplicateKeyError("unique _id")
                return None
            if count is None:
                if not upsert:
                    return None
                self.documents[key] = {"count": 0, **update["$setOnInsert"]}
            self.documents[key]["count"] += update["$inc"]["count"]
            return self.documents[key].copy()


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    monkeypatch.setenv("LIVE_REQUESTS_PER_MINUTE", "12")
    monkeypatch.setenv("LIVE_REQUESTS_PER_DAY", "100")


def test_concurrent_requests_and_restarted_limiter_share_capacity():
    store = AtomicCounterStore()
    first, restarted = UsageLimiter(store), UsageLimiter(store)

    async def exercise():
        results = await asyncio.gather(*[
            (first if i % 2 else restarted).reserve(now=NOW) for i in range(40)
        ], return_exceptions=True)
        assert sum(result is None for result in results) == 12
        assert all(result is None or result.status_code == 429 for result in results)
        assert sorted(doc["count"] for doc in store.documents.values()) == [12, 12]
        assert all(doc["expires_at"] > NOW for doc in store.documents.values())

    asyncio.run(exercise())
    store.create_index.assert_called_with("expires_at", expireAfterSeconds=0)


def test_day_limit_survives_minute_reset_and_resets_at_utc_midnight(monkeypatch):
    monkeypatch.setenv("LIVE_REQUESTS_PER_DAY", "2")
    quota = UsageLimiter(AtomicCounterStore())

    async def exercise():
        await quota.reserve(cost=2, now=NOW)
        with pytest.raises(HTTPException) as error:
            await quota.reserve(now=NOW + timedelta(minutes=1))
        assert error.value.headers["X-Error-Code"] == "day_limit"
        assert int(error.value.headers["Retry-After"]) > 0
        await quota.reserve(cost=2, now=NOW.replace(hour=0, minute=0, second=0) + timedelta(days=1))

    asyncio.run(exercise())


def test_bulk_reservation_is_weighted_and_does_not_partially_increment():
    store = AtomicCounterStore()
    quota = UsageLimiter(store)

    async def exercise():
        await quota.reserve(cost=10, now=NOW)
        with pytest.raises(HTTPException):
            await quota.reserve(cost=3, now=NOW)
        assert all(doc["count"] == 10 for doc in store.documents.values())

    asyncio.run(exercise())


def test_initial_insert_collision_retries_conditional_update():
    collection = Mock()
    collection.create_index = AsyncMock()
    collection.find_one_and_update = AsyncMock(side_effect=[
        DuplicateKeyError("competing insert"), {"count": 2}, {"count": 2},
    ])
    asyncio.run(UsageLimiter(collection).reserve(now=NOW))
    calls = collection.find_one_and_update.call_args_list
    assert [call.kwargs["upsert"] for call in calls] == [True, False, True]
    assert calls[0].args == calls[1].args


@pytest.mark.parametrize("value,status", [("0", 429), ("-1", 503), ("bad", 503)])
def test_disabled_or_invalid_limits_fail_closed(monkeypatch, value, status):
    monkeypatch.setenv("LIVE_REQUESTS_PER_MINUTE", value)
    with pytest.raises(HTTPException) as error:
        asyncio.run(UsageLimiter(AtomicCounterStore()).reserve(now=NOW))
    assert error.value.status_code == status


def test_unavailable_counter_store_fails_closed():
    collection = Mock()
    collection.create_index = AsyncMock(side_effect=ServerSelectionTimeoutError("private connection string"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(UsageLimiter(collection).reserve(now=NOW))
    assert error.value.status_code == 503
    assert "private" not in error.value.detail
    collection.find_one_and_update.assert_not_called()


@pytest.mark.parametrize("endpoint", ["search", "resources", "upload", "resources/bulk"])
def test_quota_rejects_all_expensive_routes_before_work(client, db, monkeypatch, endpoint):
    reservation = AsyncMock(side_effect=HTTPException(429, "Daily allowance reached", headers={"Retry-After": "60"}))
    monkeypatch.setattr(limiter, "reserve", reservation)
    summary = Mock()
    embed = Mock()
    upload = Mock()
    monkeypatch.setattr(resources, "summarize_link", summary)
    monkeypatch.setattr(resources, "process_upload", upload)
    monkeypatch.setattr(search, "get_embedding", embed)
    monkeypatch.setattr(resources, "get_embedding", embed)
    resource = {"title": "Sample", "description": "Lesson", "media_type": "article",
                "media_link": "https://example.com", "course": "CS"}
    if endpoint == "search":
        response = client.post("/search", json={"query": "Explain limits"})
    elif endpoint == "upload":
        response = client.post("/upload", data={"title": "T", "description": "D", "course": "CS"},
                               files={"file": ("notes.txt", b"lesson")})
    else:
        monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
        response = client.post("/" + endpoint, json=[resource, resource] if endpoint.endswith("bulk") else resource,
                               headers={"Authorization": "Bearer test-admin"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    if endpoint.endswith("bulk"):
        reservation.assert_awaited_once_with(cost=2)
    summary.assert_not_called()
    embed.assert_not_called()
    upload.assert_not_called()
    db.insert_one.assert_not_called()
    db.insert_many.assert_not_called()


def test_cors_exposes_retry_headers_only_to_configured_frontend(client):
    response = client.options("/search", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options("/search", headers={
        "Origin": "https://unlisted.example", "Access-Control-Request-Method": "POST",
    })
    assert denied.status_code == 400
