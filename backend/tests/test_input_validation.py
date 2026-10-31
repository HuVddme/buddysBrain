"""Public input validation happens before quota, processing or storage work."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bson import ObjectId
import pytest

from app.routes import resources, search
from app.services import jobs
from app.usage import limiter


METADATA = {"title": "Notes", "description": "Study notes", "course": "CS101"}
LINK = {**METADATA, "media_type": "article", "media_link": "https://example.com/notes"}


@pytest.mark.parametrize("payload", [
    {}, {"query": ""}, {"query": " \t\n\u2003 "}, {"query": "x" * 2001},
    {"query": "x" * 100000}, {"query": None}, {"query": 12}, {"query": []},
    {"query": "Question", "unexpected": "field"},
])
def test_invalid_questions_never_reserve_or_process(client, db, monkeypatch, payload):
    embed, answer = Mock(), Mock()
    monkeypatch.setattr(search, "get_embedding", embed)
    monkeypatch.setattr(search, "summarize_resources", answer)
    response = client.post("/search", json=payload)
    assert response.status_code == 422
    limiter.reserve.assert_not_awaited()
    embed.assert_not_called()
    answer.assert_not_called()
    db.aggregate.assert_not_called()


@pytest.mark.parametrize("question", ["Q", "x" * 2000])
def test_valid_question_boundaries_are_trimmed_before_retrieval(client, db, monkeypatch, question):
    class EmptyCursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    db.aggregate.return_value = EmptyCursor()
    embed = Mock(return_value=[0.1])
    answer = Mock(return_value="Answer")
    monkeypatch.setattr(search, "get_embedding", embed)
    monkeypatch.setattr(search, "summarize_resources", answer)
    response = client.post("/search", json={"query": f" \n{question}\t "})
    assert response.status_code == 200
    embed.assert_called_once_with(question)
    answer.assert_called_once_with([], question)
    limiter.reserve.assert_awaited_once()


@pytest.mark.parametrize("field,invalid", [
    ("title", " \t\n"), ("title", "x" * 201),
    ("description", "\u2003 "), ("description", "x" * 4001),
    ("course", "  "), ("course", "x" * 201),
])
@pytest.mark.parametrize("kind", ["link", "image", "document", "queued-document"])
def test_metadata_rules_match_all_submission_paths(client, db, monkeypatch, field, invalid, kind):
    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "true" if kind == "queued-document" else "false")
    process, enqueue = AsyncMock(), AsyncMock()
    monkeypatch.setattr(resources, "run_processing", process)
    monkeypatch.setattr(jobs, "enqueue", enqueue)
    if kind == "link":
        response = client.post("/resources", json={**LINK, field: invalid})
    else:
        suffix = ".png" if kind == "image" else ".txt"
        response = client.post("/upload", data={**METADATA, field: invalid},
                               files={"file": ("notes" + suffix, b"notes")})
    assert response.status_code == 422, response.text
    limiter.reserve.assert_not_awaited()
    process.assert_not_awaited()
    enqueue.assert_not_awaited()
    db.find_one.assert_not_awaited()
    db.insert_one.assert_not_awaited()


@pytest.mark.parametrize("change", [
    {"media_type": "document"}, {"media_type": "image"}, {"media_type": "other"},
    {"media_type": ""}, {"media_link": "not a URL"},
    {"media_link": "https://example.com/" + "x" * 2048},
    {"summary": "caller claim"}, {"embedding": [1]}, {"timestamp": "2026-01-01"},
])
def test_single_link_cannot_bypass_bulk_input_rules(client, db, monkeypatch, change):
    process = AsyncMock()
    monkeypatch.setattr(resources, "run_processing", process)
    response = client.post("/resources", json={**LINK, **change})
    assert response.status_code == 422
    limiter.reserve.assert_not_awaited()
    process.assert_not_awaited()
    db.insert_one.assert_not_awaited()


@pytest.mark.parametrize("kind", ["link", "image", "document", "queued-document"])
def test_metadata_maximums_are_accepted_and_trimmed_before_saving(client, db, monkeypatch, kind):
    metadata = {"title": "t" * 200, "description": "d" * 4000, "course": "c" * 200}
    padded = {key: f" \t{value}\n " for key, value in metadata.items()}
    oid = ObjectId()
    db.insert_one.return_value = SimpleNamespace(inserted_id=oid)
    db.find_one.return_value = {**LINK, **metadata, "_id": oid}
    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "true" if kind == "queued-document" else "false")
    if kind == "link":
        monkeypatch.setattr(resources, "summarize_link", Mock(return_value=("Summary", [0.1])))
        response = client.post("/resources", json={**LINK, **padded})
    elif kind == "queued-document":
        db.find_one.return_value = None
        enqueue = AsyncMock(return_value={"job_id": "test-job", "status": "queued"})
        monkeypatch.setattr(jobs, "enqueue", enqueue)
        monkeypatch.setattr(resources, "dispatch", AsyncMock(return_value=True))
        response = client.post("/upload", data=padded, files={"file": ("notes.txt", b"notes")})
        assert response.status_code == 202, response.text
        enqueue.assert_awaited_once_with(b"notes", ".txt", metadata["title"], metadata["description"], metadata["course"])
        limiter.reserve.assert_awaited_once()
        return
    else:
        monkeypatch.setattr(resources, "process_upload", Mock(return_value=SimpleNamespace(
            summary="Summary", embedding=[0.1], media_link=LINK["media_link"], document=None,
        )))
        suffix = ".png" if kind == "image" else ".txt"
        response = client.post("/upload", data=padded, files={"file": ("notes" + suffix, b"notes")})
    assert response.status_code == 200, response.text
    saved = db.insert_one.call_args.args[0]
    assert {key: saved[key] for key in metadata} == metadata
    assert saved["timestamp"]
    limiter.reserve.assert_awaited_once()
