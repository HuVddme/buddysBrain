import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from bson import ObjectId
import pytest

from app.models import SearchQuery
from app.routes import resources, search
from app.services import processing, ingestion
from app.services import documents
from app.services import links as urls

PAYLOAD = {"title": "Lesson", "description": "Fallback", "media_type": "article", "media_link": "https://example.com", "course": "CS101"}


@pytest.mark.parametrize("failure,status", [(processing.ProcessingError("Article unavailable"), 502), (RuntimeError("private upstream details"), 502)])
def test_failed_summary_is_not_embedded_or_saved(client, db, monkeypatch, failure, status):
    monkeypatch.setattr(ingestion, "summarize_article", Mock(side_effect=failure))
    embedding = Mock()
    monkeypatch.setattr(ingestion, "get_embedding", embedding)
    response = client.post("/resources", json=PAYLOAD)
    assert response.status_code == status
    assert "private upstream details" not in response.text
    db.insert_one.assert_not_called()
    embedding.assert_not_called()


def test_rejected_url_is_a_400_not_a_saved_fallback(client, db):
    response = client.post("/resources", json={**PAYLOAD, "media_link": "file:///etc/passwd"})
    assert response.status_code == 400
    db.insert_one.assert_not_called()


def test_successful_resource_returns_serializable_id(client, db, monkeypatch):
    monkeypatch.setattr(ingestion, "summarize_article", lambda url: "Actual summary")
    resource_id = ObjectId()
    db.insert_one.return_value = SimpleNamespace(inserted_id=resource_id)
    db.find_one.return_value = {**PAYLOAD, "summary": "Actual summary", "_id": resource_id}
    response = client.post("/resources", json=PAYLOAD)
    assert response.status_code == 200, response.text
    assert response.json()["_id"] == str(resource_id)
    assert db.insert_one.call_args.args[0]["summary"] == "Actual summary"


@pytest.mark.parametrize("filename,content,status", [("slides.pptx", b"test", 415), ("legacy.doc", b"test", 415), ("empty.txt", b"", 422)])
def test_invalid_uploads_do_not_call_services(client, db, monkeypatch, filename, content, status):
    service = Mock()
    monkeypatch.setattr(resources, "process_upload", service)
    response = client.post("/upload", data={"title": "Test", "description": "Test", "course": "CS"}, files={"file": (filename, content)})
    assert response.status_code == status
    service.assert_not_called()
    db.insert_one.assert_not_called()


def test_summary_failure_cleans_temp_files_and_does_not_upload(client, db, monkeypatch):
    paths = []
    def failing_summary(path):
        paths.append(Path(path))
        assert Path(path).exists()
        raise processing.ProcessingError("The document has no readable text.", 422)
    monkeypatch.setattr(ingestion, "summarize_image", failing_summary)
    cloud_upload = Mock()
    monkeypatch.setattr(ingestion.cloudinary.uploader, "upload", cloud_upload)
    response = client.post("/upload", data={"title": "Test", "description": "Test", "course": "CS"}, files={"file": ("notes.png", b"image")})
    assert response.status_code == 422
    assert len(paths) == 1 and not paths[0].parent.exists()
    cloud_upload.assert_not_called()
    db.insert_one.assert_not_called()


def test_successful_upload_cleans_files_and_has_timeout(client, db, monkeypatch):
    paths = []
    def summary(path):
        paths.append(Path(path))
        return "Good summary"
    monkeypatch.setattr(ingestion, "summarize_image", summary)
    monkeypatch.setattr(ingestion.cloudinary, "config", lambda: SimpleNamespace(cloud_name="test", api_key="test", api_secret="test"))
    cloud_upload = Mock(return_value={"secure_url": "https://example.com/file.txt"})
    monkeypatch.setattr(ingestion.cloudinary.uploader, "upload", cloud_upload)
    resource_id = ObjectId()
    db.insert_one.return_value = SimpleNamespace(inserted_id=resource_id)
    db.find_one.return_value = {**PAYLOAD, "_id": resource_id}
    response = client.post("/upload", data={"title": "Test", "description": "Test", "course": "CS"}, files={"file": ("notes.png", b"image")})
    assert response.status_code == 200, response.text
    assert not paths[0].parent.exists()
    assert cloud_upload.call_args.kwargs["timeout"] == 30
    assert db.insert_one.call_args.args[0]["summary"] == "Good summary"


def test_empty_document_never_calls_ai(tmp_path, monkeypatch):
    path = tmp_path / "empty.txt"
    path.write_text("  \n")
    ai = Mock()
    monkeypatch.setattr(documents, "generate_summary", ai)
    with pytest.raises(processing.ProcessingError) as error:
        documents.summarize_document(str(path))
    assert error.value.status_code == 422
    ai.assert_not_called()


def test_embedding_failure_also_cleans_temporary_files(monkeypatch):
    paths = []
    def summarize(path):
        paths.append(Path(path))
        return "Summary"
    monkeypatch.setattr(ingestion, "summarize_image", summarize)
    monkeypatch.setattr(ingestion, "get_embedding", Mock(side_effect=RuntimeError("embedding failed")))
    with pytest.raises(RuntimeError):
        ingestion.process_upload(b"image", ".png", "image")
    assert not paths[0].parent.exists()


def test_cloudinary_uses_environment_credentials(monkeypatch):
    import importlib
    from app.services import storage
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "own-cloud")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "test-secret")
    configure = Mock()
    monkeypatch.setattr(storage.cloudinary, "config", configure)
    importlib.reload(storage)
    configure.assert_called_once_with(cloud_name="own-cloud", api_key="test-key", api_secret="test-secret", secure=True)


def test_missing_ai_key_is_explicit():
    with pytest.raises(processing.ProcessingError) as error:
        processing.get_ai_client()
    assert error.value.status_code == 503


def test_ai_timeout_and_retries_are_bounded(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    factory = Mock()
    monkeypatch.setattr(processing, "OpenAI", factory)
    processing.get_ai_client()
    assert factory.call_args.kwargs["timeout"] == 30
    assert factory.call_args.kwargs["max_retries"] == 1


def test_search_worker_does_not_block_event_loop(monkeypatch, db):
    started = threading.Event()
    release = threading.Event()
    def slow_embedding(query):
        started.set()
        assert release.wait(2), "event loop blocked while embedding ran"
        return [0.1]
    class Cursor:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
    db.aggregate.return_value = Cursor()
    monkeypatch.setattr(search, "get_embedding", slow_embedding)
    monkeypatch.setattr(search, "summarize_resources", lambda docs, query: "answer")
    async def exercise():
        task = asyncio.create_task(search.vector_search_and_summarize(SearchQuery(query="test")))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set()
            assert not task.done()
        finally:
            release.set()
        assert (await task)["summary"] == "answer"
    asyncio.run(exercise())


@pytest.mark.parametrize("url", ["https://youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk", "https://www.youtube.com/shorts/abcdefghijk"])
def test_valid_youtube_ids(url):
    assert urls.extract_video_id(url) == "abcdefghijk"


@pytest.mark.parametrize("url", ["https://youtube.com.attacker.test/watch?v=abcdefghijk", "https://example.com/?v=abcdefghijk", "https://youtu.be/invalid"])
def test_invalid_video_urls(url):
    with pytest.raises(processing.ProcessingError):
        urls.extract_video_id(url)


def test_video_failure_is_not_returned_as_summary(monkeypatch):
    api = Mock()
    api.return_value.fetch.side_effect = RuntimeError("transcript unavailable")
    monkeypatch.setattr(urls, "YouTubeTranscriptApi", api)
    with pytest.raises(processing.ProcessingError, match="transcript is unavailable"):
        urls.summarize_video("https://youtu.be/abcdefghijk")
