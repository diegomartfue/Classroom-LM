"""
document_store.py — save uploaded course documents and read their text back.

Owns three things and nothing else:
  1. validate + extract text from an upload
  2. keep an index of what has been stored
  3. hand the text back when asked — only to someone allowed to see it

Who sees what (enforced here, on the server — every public function takes
the caller's participants.Identity):
  - Professor uploads are shared course material: every participant can
    list them, read them, and have the tutor use them.
  - A participant's own uploads are private: only that participant can
    list, read, delete, or have the tutor use them. Another participant
    asking for one gets exactly the same "not found" as for an id that
    never existed, so ids can't even be probed.

Storage layout (relative to the backend directory), one folder per owner:
    uploads/shared/index.json                 shared (professor) documents
    uploads/shared/{doc_id}.txt | {doc_id}{ext}
    uploads/participants/{code}/index.json    one participant's own uploads
    uploads/participants/{code}/{doc_id}.txt | {doc_id}{ext}

Original file names (which can identify a student, e.g. JaneSmith_HW3.pdf)
are kept only in the owner's index, for display back to that owner. They
are never put into a model prompt for a participant's own upload
(get_context labels it "Your uploaded document N"), so the tutor can't
repeat one into a saved conversation or the research export.

Files from before this layout (flat uploads/ + documents.json) are not
visible to anyone; see README "Uploads and privacy".

Nothing here imports the orchestrator, and the orchestrator does not import
this. LLM calls happen only for scanned PDFs and images, which have no text
to extract by ordinary means.
"""

import io
import json
import os
import re
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
# Module attribute (not a constant baked into defaults) so tests can point
# it at a temp folder.
UPLOAD_ROOT = os.path.join(_BACKEND_DIR, "uploads")

SHARED = "shared"
PRIVATE = "private"

# doc_ids are generated here (12 hex chars) and used in file paths, so an id
# from a request must match exactly or it's treated as not found.
_DOC_ID_RE = re.compile(r"^[0-9a-f]{12}$")

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


class DocumentForbidden(DocumentError):
    """The caller can see this document but may not change it (a participant
    deleting shared course material)."""


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def _space_dir(scope: str, code: str | None = None) -> str:
    if scope == SHARED:
        return os.path.join(UPLOAD_ROOT, "shared")
    # participants.normalize() already restricts codes to [A-Z0-9-]; checked
    # again here because this becomes a directory name.
    if not code or not re.fullmatch(r"[A-Z0-9-]{2,32}", code):
        raise DocumentError("Invalid participant code.")
    return os.path.join(UPLOAD_ROOT, "participants", code)


def _load_index(space: str) -> list:
    path = os.path.join(space, "index.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(space: str, records: list) -> None:
    os.makedirs(space, exist_ok=True)
    path = os.path.join(space, "index.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _visible_spaces(identity) -> list[str]:
    """Shared material first, then the caller's own folder. Nothing else
    is ever searched, which is what keeps other participants' files out."""
    spaces = [_space_dir(SHARED)]
    if not identity.is_professor:
        spaces.append(_space_dir(PRIVATE, identity.code))
    return spaces


def _find(doc_id: str, identity) -> tuple[str, dict]:
    if isinstance(doc_id, str) and _DOC_ID_RE.match(doc_id):
        for space in _visible_spaces(identity):
            for record in _load_index(space):
                if record.get("doc_id") == doc_id:
                    return space, record
    raise DocumentError(f"No document found with id '{doc_id}'.")


def _public(record: dict, identity) -> dict:
    """What the API returns about a document. The owner field never leaves
    the server; the file name is shown because the caller is either the
    owner (private) or looking at shared course material."""
    out = {k: v for k, v in record.items() if k != "owner"}
    out["mine"] = record.get("scope") == PRIVATE or identity.is_professor
    return out


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

def save_document(filename: str, data: bytes, identity, course: str = "default") -> dict:
    """
    Validate, extract, and store one uploaded file: shared course material
    when a professor uploads it, private to the uploader otherwise.
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

    scope = SHARED if identity.is_professor else PRIVATE
    space = _space_dir(scope, identity.code)
    os.makedirs(space, exist_ok=True)
    doc_id = uuid.uuid4().hex[:12]

    # Stored filenames are built from doc_id, never from user input, so a
    # crafted filename cannot escape the owner's folder.
    with open(os.path.join(space, f"{doc_id}.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(space, f"{doc_id}{ext}"), "wb") as fh:
        fh.write(data)

    record = {
        "doc_id": doc_id,
        "filename": os.path.basename(filename),
        "scope": scope,
        "owner": identity.code,
        "course": course or "default",
        "extension": ext,
        "bytes": len(data),
        "chars": len(text),
        "words": len(text.split()),
        "extraction_method": method,
        "truncated": truncated,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    records = _load_index(space)
    records.append(record)
    _save_index(space, records)
    return _public(record, identity)


def list_documents(identity, course: str | None = None) -> list:
    """Shared course material plus the caller's own uploads, newest first."""
    records = [r for space in _visible_spaces(identity) for r in _load_index(space)]
    if course:
        records = [r for r in records if r.get("course") == course]
    records.sort(key=lambda r: r.get("uploaded_at", ""), reverse=True)
    return [_public(r, identity) for r in records]


def get_document(doc_id: str, identity) -> dict:
    """One record plus its full text, if the caller may see it. Raises
    DocumentError (not found) otherwise."""
    space, record = _find(doc_id, identity)
    path = os.path.join(space, f"{doc_id}.txt")
    if not os.path.exists(path):
        raise DocumentError(
            f"The text for '{record.get('filename')}' is missing from disk."
        )
    with open(path, "r", encoding="utf-8") as fh:
        return {**_public(record, identity), "text": fh.read()}


def delete_document(doc_id: str, identity) -> dict:
    """Remove a document the caller owns. Participants can't delete shared
    course material; only a professor can."""
    space, record = _find(doc_id, identity)
    if record.get("scope") == SHARED and not identity.is_professor:
        raise DocumentForbidden("Shared course material can only be removed by the professor.")

    for path in (os.path.join(space, f"{doc_id}.txt"),
                 os.path.join(space, f"{doc_id}{record.get('extension', '')}")):
        try:
            os.remove(path)
        except OSError:
            pass
    _save_index(space, [r for r in _load_index(space) if r.get("doc_id") != doc_id])
    return {"deleted": doc_id}


def visible_ids(doc_ids: list, identity) -> list:
    """The subset of doc_ids the caller may see, in order. Lets the tutor
    use the attachable ones even when a request also names something the
    caller can't (stale id, or someone else's)."""
    out = []
    for doc_id in doc_ids or []:
        try:
            _find(doc_id, identity)
        except DocumentError:
            continue
        out.append(doc_id)
    return out


def get_context(doc_ids: list, identity) -> str:
    """
    Hand back the text to feed a model, for one or more documents the
    caller may see (any other id raises DocumentError, same as missing).

    Shared material is labelled with its file name. A participant's own
    upload is labelled "Your uploaded document N" instead: its file name
    may carry the student's name, and whatever is in the prompt can end up
    in the tutor's reply, the saved conversation, and the research export.

    This is the seam. Today it returns whole documents. When the pile grows
    past what fits in a prompt, the retrieval strategy changes *inside this
    function* and every feature above it stays exactly as written.
    """
    if not doc_ids:
        return ""
    blocks = []
    own_count = 0
    for doc_id in doc_ids:
        record = get_document(doc_id, identity)
        if record.get("scope") == SHARED:
            label = f"Course material: {record['filename']}"
        else:
            own_count += 1
            label = f"Your uploaded document {own_count}"
        blocks.append(
            f"--- BEGIN DOCUMENT: {label} ---\n"
            f"{record['text']}\n"
            f"--- END DOCUMENT: {label} ---"
        )
    return "\n\n".join(blocks)
