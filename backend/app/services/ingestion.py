"""Synchronous ingestion operations shared by HTTP handlers and future workers."""
from pathlib import Path
import tempfile
from dataclasses import dataclass

import cloudinary.uploader

from .storage import cloudinary
from .documents import summarize_document_text
from .passages import prepare_document
from .images import summarize_image
from .links import summarize_article, summarize_video
from .embeddings import get_embedding
from .processing import ProcessingError


def summarize_link(media_type, media_link):
    if media_type == "article":
        summary = summarize_article(media_link)
    elif media_type == "video":
        summary = summarize_video(media_link)
    else:
        raise ProcessingError("Upload documents and images through the file upload form.", 400)
    if not summary or not summary.strip():
        raise ProcessingError("No summary could be generated for this resource.")
    return summary.strip(), get_embedding(summary)


@dataclass
class ProcessedUpload:
    summary: str
    embedding: list
    media_link: str
    document: dict | None = None


def process_upload(contents, suffix, media_type):
    document = None
    if media_type == "document":
        document = prepare_document(contents, suffix)
        summary = summarize_document_text("\n\n".join(p["text"] for p in document["pages"]))
    # Cleanup is guaranteed even if parsing, an API call or embedding fails.
    else:
        with tempfile.TemporaryDirectory(prefix="buddys-brain-") as directory:
            path = Path(directory) / f"resource{suffix}"
            path.write_bytes(contents)
            summary = summarize_image(str(path))
    if not summary or not summary.strip():
        raise ProcessingError("The file has no readable educational content.", 422)
    embedding = get_embedding(summary)
    # Avoid creating a cloud asset when summarization has already failed.
    settings = cloudinary.config()
    if not all((settings.cloud_name, settings.api_key, settings.api_secret)):
        raise ProcessingError("File storage is not configured.", 503)
    uploaded = cloudinary.uploader.upload(
        contents, resource_type="raw" if media_type == "document" else "image", timeout=30,
    )
    return ProcessedUpload(summary, embedding, uploaded["secure_url"], document)
