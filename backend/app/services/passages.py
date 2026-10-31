"""Token-bounded, overlapping excerpts of original extracted document text."""
from hashlib import sha256
from pathlib import Path
import tempfile

from .documents import extract_document_pages
from .embeddings import get_embedding_model, _model_lock
from .processing import ProcessingError

PASSAGE_SCHEMA_VERSION = 1
MAX_PASSAGES = 256
TOKEN_WINDOW = 200
TOKEN_OVERLAP = 40


def split_pages(pages, tokenizer, max_seq_length):
    budget = min(TOKEN_WINDOW, max_seq_length - tokenizer.num_special_tokens_to_add(pair=False))
    if budget <= TOKEN_OVERLAP:
        raise ProcessingError("The document embedding model is not configured correctly.", 503)
    passages = []
    for page in pages:
        text = page["text"]
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                            truncation=False)["offset_mapping"]
        start = 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            char_start, char_end = offsets[start][0], offsets[end - 1][1]
            excerpt = text[char_start:char_end]
            # Splitting inside a word can change tokenization at its boundary.
            # Check the actual excerpt rather than relying on a word count.
            while len(tokenizer.encode(excerpt, add_special_tokens=True)) > max_seq_length:
                end -= 1
                if end <= start:
                    raise ProcessingError("A document passage could not be tokenized.", 422)
                char_end = offsets[end - 1][1]
                excerpt = text[char_start:char_end]
            if excerpt.strip():
                passages.append({"ordinal": len(passages) + 1, "page": page["page"],
                                 "start": char_start, "end": char_end, "text": excerpt})
                if len(passages) > MAX_PASSAGES:
                    raise ProcessingError("This document is too long for live processing. Split it into smaller files.", 413)
            if end == len(offsets):
                break
            start = max(start + 1, end - TOKEN_OVERLAP)
    if not passages:
        raise ProcessingError("The document has no readable text.", 422)
    return passages


def prepare_document(contents: bytes, suffix: str) -> dict:
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise ProcessingError("Supported documents: PDF, DOCX and TXT.", 415)
    with tempfile.TemporaryDirectory(prefix="buddys-brain-") as directory:
        path = Path(directory) / f"resource{suffix}"
        path.write_bytes(contents)
        try:
            pages = extract_document_pages(str(path))
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("The document could not be read. Use an unencrypted PDF, DOCX or UTF-8 TXT file.", 422) from exc
    with _model_lock:
        model = get_embedding_model()
    passages = split_pages(pages, model.tokenizer, model.max_seq_length)
    vectors = model.encode([p["text"] for p in passages], batch_size=16,
                           show_progress_bar=False).tolist()
    if len(vectors) != len(passages) or any(len(v) != 384 for v in vectors):
        raise ProcessingError("Document embeddings have an unexpected shape.", 503)
    for passage, vector in zip(passages, vectors):
        passage["embedding"] = vector
    return {"pages": pages, "passages": passages, "sha256": sha256(contents).hexdigest()}
