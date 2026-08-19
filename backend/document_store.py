"""
document_store.py — save uploaded course documents and read their text back.

Owns three things and nothing else:
  1. validate + extract text from an upload
  2. keep an index of what has been stored
  3. hand the text back when asked

Storage layout (relative to the backend directory):
    uploads/{doc_id}.txt     extracted plain text
    uploads/{doc_id}{ext}    the original file, kept for reference
    documents.json           the index

Nothing here imports the orchestrator, and the orchestrator does not import
this. LLM calls happen only for scanned PDFs and images, which have no text
to extract by ordinary means.
"""

import io
import json
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

from model_config import SONNET_MODEL
# Aliased to avoid colliding with this module's own extract_text(filename, data),
# which extracts text from an uploaded FILE (not from a Claude response).
from response_utils import extract_text as extract_response_text

load_dotenv()

# Anchored to the backend directory so it does not matter where uvicorn
# was launched from.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_UPLOAD_DIR = os.path.join(_BACKEND_DIR, "uploads")
_INDEX_PATH = os.path.join(_BACKEND_DIR, "documents.json")

# Anything bigger than this is rejected outright.
MAX_FILE_BYTES = 20 * 1024 * 1024          # 20 MB
# Below this many characters we assume extraction failed (scanned PDF).
MIN_TEXT_CHARS = 200
# Images legitimately hold less text than a document — a photo of one worked
# problem is short. Judge them on a lower bar.
MIN_IMAGE_TEXT_CHARS = 20
# Rough ceiling so one document cannot swallow the whole model context.
MAX_TEXT_CHARS = 400_000

_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md",
                        ".png", ".jpg", ".jpeg", ".gif", ".webp")


class DocumentError(Exception):
    """Raised when an upload cannot be accepted. The message is user-facing."""


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    os.makedirs(_UPLOAD_DIR, exist_ok=True)


def _load_index() -> list:
    if not os.path.exists(_INDEX_PATH):
        return []
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(records: list) -> None:
    _ensure_dirs()
    tmp = f"{_INDEX_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, _INDEX_PATH)


def _text_path(doc_id: str) -> str:
    return os.path.join(_UPLOAD_DIR, f"{doc_id}.txt")


def _safe_extension(filename: str) -> str:
    """Return a lowercase extension we recognise, or raise."""
    _, ext = os.path.splitext(filename or "")
    ext = ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentError(
            f"Unsupported file type '{ext or 'unknown'}'. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return ext


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"Could not open this PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        raise DocumentError(
            "This PDF is password protected. Remove the password and upload again."
        )

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n\n".join(pages).strip()


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise DocumentError(
            "Word support is not installed on this server (pip install python-docx)."
        ) from exc
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"Could not open this Word file: {exc}") from exc
    return "\n".join(p.text for p in doc.paragraphs).strip()


def _extract_plaintext(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    raise DocumentError("Could not read this file as text.")


def _anthropic_client():
    """Shared client for the two vision paths. Raises if the key is missing."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise DocumentError(
            "Reading scans and images requires ANTHROPIC_API_KEY, which is not set."
        )
    return anthropic.Anthropic(api_key=api_key)


def _response_text(response) -> str:
    return extract_response_text(response).strip()


_TRANSCRIBE_INSTRUCTION = (
    "Transcribe everything written here to plain text, in reading order. "
    "Include all equations, keeping subscripts, superscripts, vector notation, "
    "and signs exactly as written. Describe any diagram briefly in square "
    "brackets. Do not solve anything, do not correct anything, do not "
    "summarise. Output only the transcription."
)


def _extract_pdf_via_vision(data: bytes) -> str:
    """
    Fallback for scanned PDFs that carry no text layer. Sends the PDF itself
    to Claude and asks for a transcription. Costs an API call, so this only
    runs when plain extraction came back essentially empty.
    """
    import base64
    client = _anthropic_client()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=10500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _TRANSCRIBE_INSTRUCTION},
                ],
            }],
        )
    except Exception as exc:
        raise DocumentError(f"Could not read this scanned PDF: {exc}") from exc
    return _response_text(response)


def _extract_image(data: bytes, ext: str) -> str:
    """
    Read text out of a photo or screenshot using Claude vision. Handles
    handwriting, which pytesseract cannot. Transcription is best-effort:
    subscripts, vector bars, and leading minus signs are the usual misses.
    """
    import base64
    client = _anthropic_client()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=5200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _IMAGE_EXTENSIONS[ext],
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _TRANSCRIBE_INSTRUCTION},
                ],
            }],
        )
    except Exception as exc:
        raise DocumentError(f"Could not read this image: {exc}") from exc
    return _response_text(response)


def extract_text(filename: str, data: bytes) -> tuple:
    """
    Return ``(text, extraction_method)``.

    extraction_method is "text" for a plain extraction and "vision" when a
    model transcribed it — callers may want to treat the latter as less
    reliable, since handwriting and scans do not transcribe perfectly.
    """
    ext = _safe_extension(filename)

    if ext == ".pdf":
        text = _extract_pdf(data)
        if len(text) >= MIN_TEXT_CHARS:
            return text, "text"
        # Almost nothing came out: treat it as a scan and try vision once.
        text = _extract_pdf_via_vision(data)
        if len(text) < MIN_TEXT_CHARS:
            raise DocumentError(
                "No readable text could be extracted from this PDF. "
                "If it is a scan, try a higher-quality version."
            )
        return text, "vision"

    if ext in _IMAGE_EXTENSIONS:
        text = _extract_image(data, ext)
        if len(text) < MIN_IMAGE_TEXT_CHARS:
            raise DocumentError("No readable text was found in this image.")
        return text, "vision"

    if ext == ".docx":
        text = _extract_docx(data)
    else:
        text = _extract_plaintext(data)

    if len(text) < MIN_TEXT_CHARS:
        raise DocumentError(
            "This file contains almost no readable text "
            f"({len(text)} characters). Nothing to work with."
        )
    return text, "text"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_document(filename: str, data: bytes, course: str = "default") -> dict:
    """
    Validate, extract, and store one uploaded file.
    Raises DocumentError with a user-facing message on any rejection.
    """
    if not data:
        raise DocumentError("That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        mb = len(data) / (1024 * 1024)
        raise DocumentError(
            f"That file is {mb:.1f} MB. The limit is "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    ext = _safe_extension(filename)
    text, method = extract_text(filename, data)

    truncated = False
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        truncated = True

    _ensure_dirs()
    doc_id = uuid.uuid4().hex[:12]

    # Stored filenames are built from doc_id, never from user input, so a
    # crafted filename cannot escape the uploads directory.
    with open(_text_path(doc_id), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(_UPLOAD_DIR, f"{doc_id}{ext}"), "wb") as fh:
        fh.write(data)

    record = {
        "doc_id": doc_id,
        "filename": os.path.basename(filename),
        "course": course or "default",
        "extension": ext,
        "bytes": len(data),
        "chars": len(text),
        "words": len(text.split()),
        "extraction_method": method,
        "truncated": truncated,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    records = _load_index()
    records.append(record)
    _save_index(records)
    return record


def list_documents(course: str | None = None) -> list:
    """Return stored document records, newest first."""
    records = _load_index()
    if course:
        records = [r for r in records if r.get("course") == course]
    return sorted(records, key=lambda r: r.get("uploaded_at", ""), reverse=True)


def get_document(doc_id: str) -> dict:
    """Return one record plus its full text. Raises DocumentError if missing."""
    for record in _load_index():
        if record.get("doc_id") == doc_id:
            path = _text_path(doc_id)
            if not os.path.exists(path):
                raise DocumentError(
                    f"The text for '{record.get('filename')}' is missing from disk."
                )
            with open(path, "r", encoding="utf-8") as fh:
                return {**record, "text": fh.read()}
    raise DocumentError(f"No document found with id '{doc_id}'.")


def delete_document(doc_id: str) -> dict:
    """Remove a document's files and its index entry."""
    records = _load_index()
    remaining = [r for r in records if r.get("doc_id") != doc_id]
    if len(remaining) == len(records):
        raise DocumentError(f"No document found with id '{doc_id}'.")

    for record in records:
        if record.get("doc_id") == doc_id:
            for path in (_text_path(doc_id),
                         os.path.join(_UPLOAD_DIR,
                                      f"{doc_id}{record.get('extension', '')}")):
                try:
                    os.remove(path)
                except OSError:
                    pass

    _save_index(remaining)
    return {"deleted": doc_id}


def get_context(doc_ids: list) -> str:
    """
    Hand back the text to feed a model, for one or more documents.

    This is the seam. Today it returns whole documents. When the pile grows
    past what fits in a prompt, the retrieval strategy changes *inside this
    function* and every feature above it stays exactly as written.
    """
    if not doc_ids:
        return ""
    blocks = []
    for doc_id in doc_ids:
        record = get_document(doc_id)
        blocks.append(
            f"--- BEGIN DOCUMENT: {record['filename']} ---\n"
            f"{record['text']}\n"
            f"--- END DOCUMENT: {record['filename']} ---"
        )
    return "\n\n".join(blocks)