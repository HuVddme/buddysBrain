import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException, Request
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import pytest

from app.routes import resources, search
from app.usage import UsageLimiter, limiter, visitor_key


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
    for key, value in {'VISITOR_REQUESTS_PER_MINUTE': '4', 'VISITOR_REQUESTS_PER_DAY': '20',
                       'VISITOR_SUBMISSIONS_PER_MINUTE': '2', 'VISITOR_SUBMISSIONS_PER_DAY': '5'}.items():
        monkeypatch.setenv(key, value)


def request_for_ip(address='203.0.113.1', headers=()):
    return Request({'type': 'http', 'method': 'POST', 'path': '/search',
                    'client': (address, 1234), 'headers': list(headers)})


def test_visitor_identity_ignores_spoofed_headers_off_vercel(monkeypatch):
    monkeypatch.delenv('VERCEL', raising=False)
    plain = visitor_key(request_for_ip())
    spoofed = visitor_key(request_for_ip(headers=[(b'x-forwarded-for', b'1.1.1.1'),
                                                  (b'x-vercel-forwarded-for', b'8.8.8.8')]))
    assert plain == spoofed and '203.0.113.1' not in plain and len(plain) == 64
    assert plain != visitor_key(request_for_ip('203.0.113.2'))


def test_vercel_uses_only_its_verified_header(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    a = visitor_key(request_for_ip(headers=[(b'x-vercel-forwarded-for', b'203.0.113.3')]))
    b = visitor_key(request_for_ip('203.0.113.9', headers=[(b'x-vercel-forwarded-for', b'203.0.113.3'),
                                                       (b'x-forwarded-for', b'8.8.8.8')]))
    assert a == b
    for headers in [[], [(b'x-forwarded-for', b'8.8.8.8')], [(b'x-vercel-forwarded-for', b'1.1.1.1, 8.8.8.8')]]:
        with pytest.raises(HTTPException) as error:
            visitor_key(request_for_ip(headers=headers))
        assert error.value.status_code == 503


def test_ip_normalization_and_hash_secret(monkeypatch):
    monkeypatch.delenv('VERCEL', raising=False)
    assert visitor_key(request_for_ip('2001:db8:abcd:1::1')) == visitor_key(request_for_ip('2001:db8:abcd:1::999'))
    assert visitor_key(request_for_ip('2001:db8:abcd:1::1')) != visitor_key(request_for_ip('2001:db8:abcd:2::1'))
    assert visitor_key(request_for_ip('::ffff:203.0.113.1')) == visitor_key(request_for_ip('203.0.113.1'))
    monkeypatch.delenv('VISITOR_RATE_LIMIT_SECRET')
    monkeypatch.setenv('RESOURCE_ADMIN_TOKEN', 'existing-admin-secret')
    assert len(visitor_key(request_for_ip())) == 64
    monkeypatch.delenv('RESOURCE_ADMIN_TOKEN')
    with pytest.raises(HTTPException) as error:
        visitor_key(request_for_ip())
    assert error.value.status_code == 503


def test_one_visitor_cannot_spend_other_visitors_capacity_under_concurrency():
    store = AtomicCounterStore()
    quota, restarted = UsageLimiter(store), UsageLimiter(store)
    async def run():
        results = await asyncio.gather(*[
            (quota if i % 2 else restarted).reserve(visitor_key='visitor-a', now=NOW) for i in range(40)
        ], return_exceptions=True)
        assert sum(r is None for r in results) == 4
        assert all(r is None or r.headers['X-Error-Code'] == 'visitor_minute_limit' for r in results)
        assert {row['count'] for key, row in store.documents.items() if key.startswith('global:')} == {4}
        await restarted.reserve(visitor_key='visitor-b', now=NOW)
        assert {row['count'] for key, row in store.documents.items() if key.startswith('global:')} == {5}
    asyncio.run(run())


def test_visitor_daily_limit_survives_restart_and_minute_reset():
    store = AtomicCounterStore()
    async def run():
        for minute in range(5):
            await UsageLimiter(store).reserve(cost=4, visitor_key='a', now=NOW + timedelta(minutes=minute))
        with pytest.raises(HTTPException) as error:
            await UsageLimiter(store).reserve(visitor_key='a', now=NOW + timedelta(minutes=6))
        assert error.value.headers['X-Error-Code'] == 'visitor_day_limit'
        assert int(error.value.headers['Retry-After']) > 0
        assert store.documents[f'global:day:{NOW.replace(hour=0, minute=0, second=0).isoformat()}']['count'] == 20
        await UsageLimiter(store).reserve(visitor_key='b', now=NOW + timedelta(minutes=6))
        await UsageLimiter(store).reserve(visitor_key='a', now=NOW + timedelta(days=1))
    asyncio.run(run())


def test_submissions_have_stricter_limits_but_questions_remain_available():
    store = AtomicCounterStore()
    quota = UsageLimiter(store)
    async def run():
        await quota.reserve(cost=2, visitor_key='a', submission=True, now=NOW)
        with pytest.raises(HTTPException) as error:
            await quota.reserve(visitor_key='a', submission=True, now=NOW)
        assert error.value.headers['X-Error-Code'] == 'submission_minute_limit'
        await quota.reserve(visitor_key='a', now=NOW)
        await quota.reserve(cost=2, visitor_key='a', submission=True, now=NOW + timedelta(minutes=1))
        await quota.reserve(visitor_key='a', submission=True, now=NOW + timedelta(minutes=2))
        with pytest.raises(HTTPException) as error:
            await quota.reserve(visitor_key='a', submission=True, now=NOW + timedelta(minutes=3))
        assert error.value.headers['X-Error-Code'] == 'submission_day_limit'
        await quota.reserve(visitor_key='b', submission=True, now=NOW + timedelta(minutes=3))
    asyncio.run(run())


def test_global_cap_still_applies_across_visitors(monkeypatch):
    monkeypatch.setenv('LIVE_REQUESTS_PER_DAY', '2')
    quota = UsageLimiter(AtomicCounterStore())
    async def run():
        await quota.reserve(visitor_key='a', now=NOW)
        await quota.reserve(visitor_key='b', now=NOW)
        with pytest.raises(HTTPException) as error:
            await quota.reserve(visitor_key='c', now=NOW)
        assert error.value.headers['X-Error-Code'] == 'day_limit'
    asyncio.run(run())


@pytest.mark.parametrize('endpoint', ['search', 'resources', 'upload', 'ingestion/00000000-0000-4000-8000-000000000000/retry'])
def test_public_routes_enforce_visitor_limits_before_work(client, db, monkeypatch, endpoint):
    from app.routes import ingestion
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setenv('VISITOR_REQUESTS_PER_MINUTE' if endpoint == 'search' else 'VISITOR_SUBMISSIONS_PER_MINUTE', '0')
    quota = UsageLimiter(AtomicCounterStore())
    monkeypatch.setattr(limiter, 'reserve', quota.reserve)
    processing, retry = AsyncMock(), AsyncMock()
    monkeypatch.setattr(resources, 'run_processing', processing)
    monkeypatch.setattr(search, 'run_processing', processing)
    monkeypatch.setattr(ingestion.jobs, 'retry', retry)
    if endpoint == 'upload':
        response = client.post('/upload', data={'title': 'T', 'description': 'D', 'course': 'CS'}, files={'file': ('notes.txt', b'notes')})
    elif endpoint == 'resources':
        response = client.post('/resources', json={'title': 'T', 'description': 'D', 'course': 'CS', 'media_type': 'article', 'media_link': 'https://example.com'})
    else:
        response = client.post('/' + endpoint, json={'query': 'Question'} if endpoint == 'search' else {})
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0
    assert response.headers['X-Error-Code'] == ('visitor_minute_limit' if endpoint == 'search' else 'submission_minute_limit')
    processing.assert_not_called()
    retry.assert_not_called()
    db.insert_one.assert_not_called()


@pytest.mark.parametrize('setting', ['VISITOR_REQUESTS_PER_MINUTE', 'VISITOR_REQUESTS_PER_DAY',
                                   'VISITOR_SUBMISSIONS_PER_MINUTE', 'VISITOR_SUBMISSIONS_PER_DAY'])
def test_invalid_visitor_settings_fail_closed(setting, monkeypatch):
    monkeypatch.setenv(setting, 'invalid')
    with pytest.raises(HTTPException) as error:
        asyncio.run(UsageLimiter(AtomicCounterStore()).reserve(visitor_key='a', submission=True, now=NOW))
    assert error.value.status_code == 503


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
