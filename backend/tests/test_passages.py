import asyncio
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import OperationFailure
import pytest

from app.routes import resources, search, passage_admin
from app.services import passages, passage_store, ingestion, answers
from app.services.processing import ProcessingError
from app.services.retrieval import group_passages, passage_pipeline

RID = ObjectId("507f1f77bcf86cd799439011")
ADMIN = {"Authorization": "Bearer test-admin"}
TEXT = "Cedar can search course notes and use a calculator. It cannot delete documents."
BASE = {"_id": RID, "title": "Cedar notes", "media_type": "document", "summary": "An AI lesson.",
        "media_link": "https://example.com/notes.pdf", "description": "Study notes", "course": "AI"}


def prepared():
    return {"pages": [{"page": 2, "text": TEXT}], "sha256": sha256(b"original").hexdigest(),
            "passages": [{"ordinal": 1, "page": 2, "text": TEXT, "start": 0, "end": len(TEXT),
                          "embedding": [0.1] * 384}]}


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.rows)
        except StopIteration:
            raise StopAsyncIteration


class CharacterTokenizer:
    """A deterministic tokenizer that also stresses long words and Unicode."""
    def __call__(self, text, **kwargs):
        return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}

    def encode(self, text, add_special_tokens=True):
        return list(range(len(text) + (2 if add_special_tokens else 0)))

    def num_special_tokens_to_add(self, pair=False):
        return 2


def test_passages_preserve_source_tokens_and_pdf_pages():
    pages = [{"page": 1, "text": "Abç " * 180}, {"page": 2, "text": "The named Birch graph: A, B, D, C, E."}]
    tokenizer = CharacterTokenizer()
    chunks = passages.split_pages(pages, tokenizer, 256)
    assert len(chunks) > 2
    for page in pages:
        selected = [c for c in chunks if c["page"] == page["page"]]
        covered = set()
        for chunk in selected:
            assert chunk["text"] == page["text"][chunk["start"]:chunk["end"]]
            assert len(tokenizer.encode(chunk["text"])) <= 256
            covered.update(range(chunk["start"], chunk["end"]))
        assert covered == set(range(len(page["text"])))
        for previous, following in zip(selected, selected[1:]):
            assert following["start"] < previous["end"]
    assert [c["ordinal"] for c in chunks] == list(range(1, len(chunks) + 1))


def test_long_unbroken_text_is_token_bounded_and_total_work_is_limited(monkeypatch):
    tokenizer = CharacterTokenizer()
    monkeypatch.setattr(passages, "MAX_PASSAGES", 2)
    with pytest.raises(ProcessingError) as error:
        passages.split_pages([{"page": None, "text": "x" * 1000}], tokenizer, 256)
    assert error.value.status_code == 413


def test_document_preparation_batches_embeddings_and_cleans_file(monkeypatch):
    seen = []
    def extract(path):
        seen.append(Path(path))
        assert seen[0].read_bytes() == b"original"
        return [{"page": None, "text": TEXT}]
    model = SimpleNamespace(tokenizer=CharacterTokenizer(), max_seq_length=256,
                            encode=Mock(return_value=SimpleNamespace(tolist=lambda: [[0.1] * 384])))
    monkeypatch.setattr(passages, "extract_document_pages", extract)
    monkeypatch.setattr(passages, "get_embedding_model", lambda: model)
    result = passages.prepare_document(b"original", ".txt")
    assert not seen[0].parent.exists()
    assert result["sha256"] == sha256(b"original").hexdigest()
    assert result["passages"][0]["text"] == TEXT
    assert result["passages"][0]["page"] is None
    assert model.encode.call_args.args[0] == [TEXT]
    assert model.encode.call_args.kwargs["batch_size"] == 16


def test_failed_extraction_cleans_temporary_document(monkeypatch):
    seen = []
    def fail(path):
        seen.append(Path(path))
        raise ProcessingError("The document has no readable text.", 422)
    monkeypatch.setattr(passages, "extract_document_pages", fail)
    with pytest.raises(ProcessingError):
        passages.prepare_document(b"bad", ".pdf")
    assert not seen[0].parent.exists()


def test_summary_failure_never_uploads_or_publishes_document(client, db, monkeypatch):
    monkeypatch.setattr(ingestion, "prepare_document", lambda *a: prepared())
    monkeypatch.setattr(ingestion, "summarize_document_text", Mock(side_effect=ProcessingError("AI unavailable")))
    cloud = Mock()
    monkeypatch.setattr(ingestion.cloudinary.uploader, "upload", cloud)
    response = client.post("/upload", data={"title": "Cedar", "description": "Notes", "course": "AI"},
                           files={"file": ("notes.pdf", b"original")})
    assert response.status_code == 502
    cloud.assert_not_called()
    db.insert_one.assert_not_called()
    resources.passage_collection.insert_many.assert_not_called()


def test_upload_publishes_complete_text_and_passages_but_hides_them_from_resource_api(client, db, monkeypatch):
    monkeypatch.setattr(resources, "process_upload", lambda *a: ingestion.ProcessedUpload(
        "An AI lesson.", [0.1] * 384, BASE["media_link"], prepared()))
    db.find_one.return_value = {**BASE, "source_pages": prepared()["pages"], "passage_count": 1}
    response = client.post("/upload", data={"title": "Cedar", "description": "Notes", "course": "AI"},
                           files={"file": ("notes.pdf", b"original")})
    assert response.status_code == 200
    assert response.json()["passage_count"] == 1
    assert "source_pages" not in response.json()
    stored = db.insert_one.call_args.args[0]
    staged = resources.passage_collection.insert_many.call_args.args[0]
    assert stored["source_pages"] == prepared()["pages"]
    assert stored["source_sha256"] == prepared()["sha256"]
    assert stored["passage_revision"] == staged[0]["revision"]
    assert stored["_id"] == staged[0]["resource_id"]
    assert staged[0]["text"] == TEXT


def test_partial_passage_write_does_not_switch_parent_revision(db):
    passage_store.passage_collection.insert_many.side_effect = OperationFailure("private database details")
    with pytest.raises(HTTPException) as error:
        asyncio.run(passage_store.publish_document({**BASE, "passage_revision": "old"}, prepared()))
    assert error.value.status_code == 503
    assert "private" not in error.value.detail
    db.update_one.assert_not_called()
    passage_store.passage_collection.delete_many.assert_awaited_once()


def test_lost_commit_acknowledgement_does_not_delete_possibly_active_passages(db):
    db.update_one.side_effect = TimeoutError()
    with pytest.raises(HTTPException) as error:
        asyncio.run(passage_store.publish_document({**BASE, "passage_revision": "old"}, prepared()))
    assert error.value.status_code == 503
    passage_store.passage_collection.delete_many.assert_not_called()


def test_concurrent_update_does_not_replace_newer_revision(db):
    db.update_one.return_value = SimpleNamespace(matched_count=0)
    with pytest.raises(HTTPException) as error:
        asyncio.run(passage_store.publish_document({**BASE, "passage_revision": "old"}, prepared()))
    assert error.value.status_code == 409
    assert db.update_one.call_args.args[0] == {"_id": RID, "passage_revision": "old", "media_type": "document"}
    deleted = passage_store.passage_collection.delete_many.call_args.args[0]
    assert deleted["revision"] != "old"


@pytest.mark.parametrize("path", [f"/resources/{RID}/passages", "/admin/passage-index"])
def test_passage_mutations_require_admin_before_database_or_processing(client, db, monkeypatch, path):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    response = client.post(path, files={"file": ("notes.txt", b"original")})
    assert response.status_code == 401
    db.find_one.assert_not_called()
    resources.passage_collection.insert_many.assert_not_called()


def test_reprocessing_updates_same_id_without_ai_or_cloudinary(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    db.find_one.return_value = dict(BASE)
    db.update_one.return_value = SimpleNamespace(matched_count=1)
    monkeypatch.setattr(resources, "prepare_document", lambda *a: prepared())
    cloud = Mock()
    monkeypatch.setattr(ingestion.cloudinary.uploader, "upload", cloud)
    response = client.post(f"/resources/{RID}/passages", headers=ADMIN,
                           files={"file": ("notes.txt", b"original")})
    assert response.json() == {"resource_id": str(RID), "passage_count": 1, "changed": True}
    db.insert_one.assert_not_called()
    cloud.assert_not_called()
    updates = db.update_one.call_args.args[1]["$set"]
    assert not {"title", "summary", "media_link", "_id"} & updates.keys()
    assert updates["source_pages"] == prepared()["pages"]


def test_same_file_reprocessing_is_noop_without_quota_or_processing(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    db.find_one.return_value = {**BASE, "source_sha256": prepared()["sha256"],
                               "passage_schema_version": 1, "passage_count": 1}
    prepare = Mock()
    monkeypatch.setattr(resources, "prepare_document", prepare)
    reserve = AsyncMock()
    monkeypatch.setattr(resources, "reserve_request", reserve)
    response = client.post(f"/resources/{RID}/passages", headers=ADMIN,
                           files={"file": ("notes.txt", b"original")})
    assert response.status_code == 200
    assert response.json()["changed"] is False
    prepare.assert_not_called()
    reserve.assert_not_called()
    db.update_one.assert_not_called()


def test_reprocess_rejects_another_file_for_already_migrated_resource(client, db, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    db.find_one.return_value = {**BASE, "source_sha256": prepared()["sha256"]}
    response = client.post(f"/resources/{RID}/passages", headers=ADMIN,
                           files={"file": ("other.txt", b"different")})
    assert response.status_code == 409
    db.update_one.assert_not_called()


def row(ordinal=1, resource=None):
    return {"_id": f"chunk-{ordinal}", "resource": resource or dict(BASE), "ordinal": ordinal,
            "page": 2, "text": TEXT, "score": 0.8}


def test_passage_evidence_excludes_duplicate_summary_and_includes_citation(client, db, monkeypatch):
    db.aggregate.return_value = Cursor([{**BASE, "score": 0.9}])
    search.passage_collection.aggregate.return_value = Cursor([row()])
    generate = Mock(return_value="Cedar cannot delete documents [P1].")
    monkeypatch.setattr(answers, "generate_summary", generate)
    response = client.post("/search", json={"query": "Can Cedar delete documents?"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["passages"][0]["text"] == TEXT
    prompt = json.loads(generate.call_args.kwargs["messages"][1]["content"])
    source = prompt["resources"][0]
    assert source["evidence_type"] == "original_passages"
    assert source["passages"][0]["citation"] == "P1"
    assert source["passages"][0]["page"] == 2
    assert "summary" not in source
    assert "embedding" not in json.dumps(results)


def test_ai_outage_preserves_original_passage_text(client, db, monkeypatch):
    db.aggregate.return_value = Cursor([])
    search.passage_collection.aggregate.return_value = Cursor([row()])
    def unavailable(*args):
        raise ProcessingError("AI unavailable", 503)
    monkeypatch.setattr(search, "summarize_resources", unavailable)
    response = client.post("/search", json={"query": "Cedar tools?"})
    assert response.status_code == 200
    assert response.json()["answer_status"] == "unavailable"
    assert response.json()["results"][0]["passages"][0]["text"] == TEXT


def test_passage_index_failure_is_not_a_silent_summary_fallback(client, db, monkeypatch):
    db.aggregate.return_value = Cursor([{**BASE, "score": 0.8}])
    search.passage_collection.aggregate.side_effect = OperationFailure("private index details")
    monkeypatch.setattr(search, "summarize_resources", lambda *a: "Based on a saved summary.")
    response = client.post("/search", json={"query": "Cedar?"})
    assert response.status_code == 200
    assert "saved summaries" in response.json()["retrieval_notice"]
    assert "private" not in response.text


def test_passage_context_has_bounded_resource_diversity():
    grouped = group_passages([row(i) for i in range(10)] + [row(1, {**BASE, "_id": ObjectId()})])
    assert len(grouped) == 2
    assert len(grouped[0]["passages"]) == 3
    assert len(grouped[1]["passages"]) == 1
    assert [p["citation"] for r in grouped for p in r["passages"]] == ["P1", "P2", "P3", "P4"]


def test_vector_join_excludes_staged_stale_and_deleted_parent_revisions():
    pipeline = passage_pipeline([0.1] * 384)
    join = next(s["$lookup"] for s in pipeline if "$lookup" in s)
    assert join["from"] == "resources"
    assert join["pipeline"][0]["$match"]["$expr"] == {"$and": [
        {"$eq": ["$_id", "$$resource_id"]}, {"$eq": ["$passage_revision", "$$revision"]}]}
    assert {"$unwind": "$resource"} in pipeline


def test_index_setup_is_idempotent_and_does_not_modify_ready_index(client, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    store = passage_admin.passage_collection
    store.create_indexes = AsyncMock()
    store.create_search_index = AsyncMock()
    store.list_search_indexes.return_value.to_list = AsyncMock(return_value=[{
        "name": passage_admin.INDEX_NAME, "status": "READY", "queryable": True,
        "type": "vectorSearch", "latestDefinition": passage_admin.INDEX_DEFINITION,
    }])
    response = client.post("/admin/passage-index", headers=ADMIN)
    assert response.json()["ready"] is True
    store.create_search_index.assert_not_called()


def test_index_setup_creates_expected_index_when_missing(client, monkeypatch):
    monkeypatch.setenv("RESOURCE_ADMIN_TOKEN", "test-admin")
    store = passage_admin.passage_collection
    store.create_indexes = AsyncMock()
    store.create_search_index = AsyncMock()
    store.list_search_indexes.return_value.to_list = AsyncMock(return_value=[])
    response = client.post("/admin/passage-index", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["ready"] is False
    index = store.create_search_index.call_args.args[0].document
    assert index["name"] == "BuddysBrainPassagesIndex"
    assert index["type"] == "vectorSearch"
    expected = json.loads((Path(__file__).parents[1] / "passage-index.json").read_text())
    assert index["definition"] == expected
