import os
import pdfplumber
import docx

from .processing import ProcessingError
from .ai import generate_summary, validate_text_size


MAX_OUTPUT_TOKENS = 500     # to enforce ~200 words

def read_pdf(file_path: str) -> str:
    with pdfplumber.open(file_path) as pdf:
        return "\n\n".join(page.extract_text() or "" for page in pdf.pages)

def read_docx(file_path: str) -> str:
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def read_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()

def extract_document_pages(file_path: str) -> list[dict]:
    """Preserve PDF page boundaries and the exact text used for retrieval."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                pages.append({"page": number, "text": page.extract_text() or ""})
                # Bound accumulated text before processing the whole file.
                validate_text_size("\n\n".join(p["text"] for p in pages))
    elif ext == ".docx":
        # DOCX has no stable page numbers independent of its renderer.
        pages = [{"page": None, "text": read_docx(file_path)}]
    elif ext == ".txt":
        pages = [{"page": None, "text": read_txt(file_path)}]
    else:
        raise ProcessingError("Supported documents: PDF, DOCX and TXT.", 415)

    full_text = "\n\n".join(page["text"] for page in pages)
    if not full_text.strip():
        raise ProcessingError("The document has no readable text.", 422)
    validate_text_size(full_text)
    return pages


def summarize_document(file_path: str) -> str:
    return summarize_document_text("\n\n".join(p["text"] for p in extract_document_pages(file_path)))


def summarize_document_text(full_text: str) -> str:
    validate_text_size(full_text)

    # Build prompt for full scan summarization
    prompt = (
        "This is a full academic document. Please provide a **detailed and clear summary** in **under 200 words**. "
        "Focus on main topics, key arguments, definitions, examples, and conclusions. Avoid missing important parts.\n\n"
        f"{full_text}"
    )

    return generate_summary(
        messages=[
            {"role": "system", "content": "You summarize academic documents for university students."},
            {"role": "user", "content": prompt}
        ],
        max_output_tokens=MAX_OUTPUT_TOKENS
    )
