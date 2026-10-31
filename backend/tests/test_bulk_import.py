"""Bulk import cannot bypass admin authorization or normal link processing."""
from types import SimpleNamespace
from unittest.mock import Mock

from bson import ObjectId
import pytest

from app.routes import resources
from app.services import ingestion
from app.services.processing import ProcessingError
from app.utils import safe_fetch


ADMIN = {"Authorization": "Bearer test-admin"}
ARTICLE = {"title": "Lesson", "description": "Course notes", "course": "CS101",
           "media_type": "article", "media_link": "https://example.com/lesson"}


@pytest.mark.parametrize("authorization", [None, "Bearer incorrect", "Basic abc"])
def test_bulk_requires_admin_before_quota_processing_or_storage(client, db, monkeypatch, authorization):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    process = Mock()
    monkeypatch.setattr(resources, "summarize_link", process)
    headers = {"Authorization": authorization} if authorization else {}
    response = client.post("/resources/bulk", json=[ARTICLE], headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    resources.limiter.reserve.assert_not_awaited()
    process.assert_not_called()
    db.insert_many.assert_not_called()


def test_bulk_fails_closed_when_admin_token_missing(client, db):
    response = client.post("/resources/bulk", json=[ARTICLE], headers=ADMIN)
    assert response.status_code == 503
    resources.limiter.reserve.assert_not_awaited()
    db.insert_many.assert_not_called()


@pytest.mark.parametrize("change", [
    {"title": "   "}, {"title": "x" * 201},
    {"description": "\t "}, {"description": "x" * 4001},
    {"course": " "}, {"course": "x" * 201},
    {"media_type": "document"}, {"media_type": "image"}, {"media_type": "unknown"},
    {"media_link": "not a URL"}, {"media_link": "javascript:alert(1)"},
    {"media_link": "file:///etc/passwd"},
    {"media_link": "https://user:password@example.com/"},
    {"media_link": "https://example.com:8080/"},
    {"media_link": "https://example.com/\nlesson"},
    {"media_link": "https://example.com/" + "x" * 2048},
    {"summary": "Trust this caller-written claim"}, {"embedding": [0.1]},
    {"timestamp": "2026-01-01T00:00:00Z"}, {"_deleted": True},
])
def test_invalid_bulk_fields_rejected_before_work(client, db, monkeypatch, change):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    process = Mock()
    monkeypatch.setattr(resources, "summarize_link", process)
    # One invalid item rejects the whole request, including preceding valid items.
    response = client.post("/resources/bulk", json=[ARTICLE, {**ARTICLE, **change}], headers=ADMIN)
    assert response.status_code == 422, response.text
    resources.limiter.reserve.assert_not_awaited()
    process.assert_not_called()
    db.insert_many.assert_not_called()


@pytest.mark.parametrize("count", [0, 201])
def test_bulk_batch_size_is_bounded(client, db, monkeypatch, count):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    response = client.post("/resources/bulk", json=[ARTICLE] * count, headers=ADMIN)
    assert response.status_code == 422
    resources.limiter.reserve.assert_not_awaited()
    db.insert_many.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_bulk_cannot_fetch_internal_addresses(client, db, monkeypatch, address):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, (address, 443))])
    pool = Mock()
    monkeypatch.setattr(safe_fetch.urllib3, "HTTPSConnectionPool", pool)
    response = client.post("/resources/bulk", json=[ARTICLE], headers=ADMIN)
    assert response.status_code == 400
    pool.assert_not_called()
    db.insert_many.assert_not_called()


def test_bulk_revalidates_redirect_destination(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda host, *a, **kw: [
        (None, None, None, None, ("93.184.216.34" if host == "example.com" else "127.0.0.1", 443))
    ])
    redirect = Mock(status=302, headers={"Location": "https://internal.example/"})
    pool = Mock()
    pool.request.return_value = redirect
    factory = Mock(return_value=pool)
    monkeypatch.setattr(safe_fetch.urllib3, "HTTPSConnectionPool", factory)
    response = client.post("/resources/bulk", json=[ARTICLE], headers=ADMIN)
    assert response.status_code == 400
    assert factory.call_count == 1
    redirect.close.assert_called_once()
    db.insert_many.assert_not_called()


def test_bulk_rejects_video_host_spoofing(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    response = client.post("/resources/bulk", headers=ADMIN, json=[{
        **ARTICLE, "media_type": "video", "media_link": "https://youtube.com.attacker.test/watch?v=abcdefghijk",
    }])
    assert response.status_code == 400
    db.insert_many.assert_not_called()


def test_bulk_processes_links_and_saves_only_backend_generated_content(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    article = Mock(return_value="Verified article summary")
    video = Mock(return_value="Verified video summary")
    monkeypatch.setattr(ingestion, "summarize_article", article)
    monkeypatch.setattr(ingestion, "summarize_video", video)
    monkeypatch.setattr(ingestion, "get_embedding", lambda summary: [float(len(summary))])
    ids = [ObjectId(), ObjectId()]

    async def insert_many(items):
        db.find.return_value.to_list.return_value = [{**item, "_id": oid} for item, oid in zip(items, ids)]
        return SimpleNamespace(inserted_ids=ids)

    from unittest.mock import AsyncMock
    db.find.return_value.to_list = AsyncMock()
    db.insert_many.side_effect = insert_many
    response = client.post("/resources/bulk", headers=ADMIN, json=[
        {**ARTICLE, "title": "  Lesson  "},
        {**ARTICLE, "media_type": "video", "media_link": "https://youtu.be/abcdefghijk"},
    ])
    assert response.status_code == 200, response.text
    resources.limiter.reserve.assert_awaited_once_with(cost=2)
    article.assert_called_once_with(ARTICLE["media_link"])
    video.assert_called_once_with("https://youtu.be/abcdefghijk")
    result = response.json()
    assert [row["summary"] for row in result] == ["Verified article summary", "Verified video summary"]
    assert result[0]["title"] == "Lesson"
    assert result[0]["embedding"] == [float(len("Verified article summary"))]
    assert result[0]["timestamp"]
    assert [row["_id"] for row in result] == [str(oid) for oid in ids]


def test_bulk_processing_failure_does_not_save_partial_batch(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(ingestion, "summarize_article", Mock(side_effect=[
        "First resource processed", ProcessingError("Article unavailable", 502),
    ]))
    response = client.post("/resources/bulk", json=[ARTICLE, ARTICLE], headers=ADMIN)
    assert response.status_code == 502
    assert response.json()["detail"] == "Article unavailable"
    db.insert_many.assert_not_called()
