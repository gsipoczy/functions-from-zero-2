"""
PDF / document text extraction via Claude.

`pdf_to_text` accepts a local file path or a URL pointing at a PDF (or an
image) and returns the extracted text. A single Claude request handles all
three requirements at once: Claude reads the body text, interprets tables, and
runs OCR/vision on any embedded images.

Large PDFs are split into page-range chunks (default 100 pages each) so they
stay within the API's per-request page limit; each chunk is extracted
separately and the results are concatenated. Splitting requires the PDF bytes,
so PDF URLs are downloaded client-side; images are never chunked and are passed
to Claude by URL when possible.

Required packages:
    pip install anthropic pypdf

Authentication:
    Set the ANTHROPIC_API_KEY environment variable (or run `ant auth login`).
"""

import base64
import io
import mimetypes
import urllib.request
from urllib.parse import urlparse

import anthropic
from pypdf import PdfReader, PdfWriter

MODEL = "claude-opus-4-8"

# Conservative default: the 200K-context path caps PDFs at 100 pages.
DEFAULT_PAGES_PER_CHUNK = 100

EXTRACTION_PROMPT = (
    "Extract ALL content from this document as clean Markdown. Specifically:\n"
    "1. Transcribe every piece of body text, in reading order.\n"
    "2. Reproduce every table as a GitHub-flavored Markdown table, preserving "
    "rows, columns, and headers.\n"
    "3. For any embedded image, figure, chart, or scan, transcribe the text it "
    "contains (OCR) and briefly describe non-text visuals in [brackets].\n\n"
    "Output only the extracted content. Do not add commentary, preamble, or a "
    "summary."
)

# Media types Claude accepts as image input.
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _is_url(source: str) -> bool:
    """Return True if `source` looks like an http(s) URL."""
    scheme = urlparse(source).scheme
    return scheme in ("http", "https")


def _guess_media_type(source: str, fallback: str = "application/pdf") -> str:
    """Best-effort MIME type from a path or URL, defaulting to PDF."""
    media_type, _ = mimetypes.guess_type(source)
    return media_type or fallback


def _read_bytes(source: str) -> bytes:
    """Read raw bytes from a local path or download them from a URL."""
    if _is_url(source):
        with urllib.request.urlopen(source) as response:
            return response.read()
    with open(source, "rb") as f:
        return f.read()


def _image_block(source: str) -> dict:
    """Build an image content block for a path or URL."""
    if _is_url(source):
        return {"type": "image", "source": {"type": "url", "url": source}}
    media_type = _guess_media_type(source, fallback="image/png")
    data = base64.standard_b64encode(_read_bytes(source)).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _pdf_chunks(data: bytes, pages_per_chunk: int) -> list[bytes]:
    """Split PDF bytes into chunks of at most `pages_per_chunk` pages.

    Returns the original bytes unchanged when the PDF already fits in one chunk.
    """
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    if total <= pages_per_chunk:
        return [data]

    chunks = []
    for start in range(0, total, pages_per_chunk):
        writer = PdfWriter()
        for page in reader.pages[start:start + pages_per_chunk]:
            writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        chunks.append(buffer.getvalue())
    return chunks


def _document_block(pdf_bytes: bytes) -> dict:
    """Build a base64 PDF document content block."""
    data = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": data,
        },
    }


def _extract(client: anthropic.Anthropic, source_block: dict) -> str:
    """Run one extraction request for a single document/image block."""
    content = [source_block, {"type": "text", "text": EXTRACTION_PROMPT}]

    # Stream so large documents don't trip the SDK's request timeout.
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError("Claude refused to process this document.")

    return "".join(block.text for block in message.content if block.type == "text")


def pdf_to_text(
    source: str,
    client: anthropic.Anthropic | None = None,
    pages_per_chunk: int = DEFAULT_PAGES_PER_CHUNK,
) -> str:
    """Extract text, tables, and image text from a PDF (or image).

    Args:
        source: A local file path or an http(s) URL to a PDF or image.
        client: Optional pre-configured Anthropic client. One is created from
            the environment if not supplied.
        pages_per_chunk: Maximum pages per Claude request for PDFs. PDFs longer
            than this are split into page ranges and extracted chunk by chunk.

    Returns:
        The extracted content as Markdown. For multi-chunk PDFs, each chunk's
        output is separated by a `--- pages N–M ---` marker.
    """

    from dotenv import load_dotenv
    load_dotenv()

    client = client or anthropic.Anthropic()

    # Images are processed directly — no page concept, no chunking.
    if _guess_media_type(source) in _IMAGE_TYPES:
        return _extract(client, _image_block(source))

    chunks = _pdf_chunks(_read_bytes(source), pages_per_chunk)
    if len(chunks) == 1:
        return _extract(client, _document_block(chunks[0]))

    parts = []
    for i, chunk in enumerate(chunks):
        start = i * pages_per_chunk + 1
        end = start + PdfReader(io.BytesIO(chunk)).get_num_pages() - 1
        text = _extract(client, _document_block(chunk))
        parts.append(f"--- pages {start}–{end} ---\n\n{text}")
    return "\n\n".join(parts)
