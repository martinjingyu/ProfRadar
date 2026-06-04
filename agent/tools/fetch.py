"""
Web and PDF fetch tools for autonomous professor research.

Tools registered:
  web_fetch     — HTTP GET a URL, extract clean readable text (HTML pages, professor homepages)
  read_url_pdf  — download a PDF from a URL and extract its text
  read_pdf      — read a local PDF file and extract its text
"""
from __future__ import annotations

import re
import tempfile
import urllib.request
from pathlib import Path

from .registry import json_result, registry

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_EXCESS_NEWLINES = re.compile(r"\n{4,}")


def _clean_text(text: str) -> str:
    """Normalize whitespace and strip boilerplate noise from extracted text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    text = _EXCESS_NEWLINES.sub("\n\n\n", text)
    return text.strip()


def _html_to_text(html: str, max_chars: int) -> str:
    """Extract readable text from HTML using BeautifulSoup; strip navigation/boilerplate."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "iframe", "noscript", "form", "button", "meta", "link"]):
        tag.decompose()

    main = (
        soup.find("main")
        or soup.find(id=re.compile(r"main|content|body", re.I))
        or soup.find(class_=re.compile(r"main|content|body", re.I))
        or soup.body
        or soup
    )
    raw = main.get_text("\n")
    lines = [ln.strip() for ln in raw.splitlines() if len(ln.strip()) > 20]
    text = _clean_text("\n".join(lines))
    return text[:max_chars]


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF (fitz) with pdfplumber as fallback."""
    # Try PyMuPDF first (fastest, handles most PDFs)
    try:
        import fitz  # PyMuPDF
        pages = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    pages.append(text.strip())
        if pages:
            return "\n\n".join(pages)
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: pdfplumber
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
        if pages:
            return "\n\n".join(pages)
    except ImportError:
        pass
    except Exception:
        pass

    # Last resort: PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        if pages:
            return "\n\n".join(pages)
    except ImportError:
        pass
    except Exception:
        pass

    return ""


# ── Tool handlers ─────────────────────────────────────────────────────────────

def _web_fetch(args: dict, runtime: dict) -> str:
    """Fetch a URL and return clean readable text."""
    url = (args.get("url") or "").strip()
    if not url:
        return json_result(success=False, error="url is required")
    max_chars = int(args.get("max_chars") or 8000)

    # Detect PDF by URL extension — redirect to PDF handler
    if url.lower().split("?")[0].endswith(".pdf"):
        return _read_url_pdf({"url": url, "max_chars": max_chars}, runtime)

    try:
        req = urllib.request.Request(url, headers=_FETCH_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw_bytes = resp.read(1_500_000)  # cap at 1.5 MB
    except Exception as exc:
        return json_result(success=False, error=f"Fetch failed: {exc}")

    # If the server actually returned a PDF, extract it differently
    if "pdf" in content_type.lower():
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            try:
                text = _extract_pdf_text(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
            text = _clean_text(text)
            truncated = len(text) > max_chars
            return json_result(
                success=True, url=url, type="pdf",
                content=text[:max_chars], truncated=truncated,
            )
        except Exception as exc:
            return json_result(success=False, error=f"PDF extraction failed: {exc}")

    # HTML / text
    try:
        html = raw_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        return json_result(success=False, error=f"Decode failed: {exc}")

    text = _html_to_text(html, max_chars * 2)  # extract more, then truncate
    truncated = len(text) > max_chars
    return json_result(
        success=True, url=url, type="html",
        content=text[:max_chars], truncated=truncated,
        note="Use a larger max_chars or call again if content was truncated." if truncated else None,
    )


def _read_url_pdf(args: dict, runtime: dict) -> str:
    """Download a PDF from a URL and extract its text."""
    url = (args.get("url") or "").strip()
    if not url:
        return json_result(success=False, error="url is required")
    max_chars = int(args.get("max_chars") or 20000)

    try:
        req = urllib.request.Request(url, headers=_FETCH_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(10_000_000)  # 10 MB cap
    except Exception as exc:
        return json_result(success=False, error=f"Failed to download PDF: {exc}")

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            text = _extract_pdf_text(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        return json_result(success=False, error=f"Failed to extract PDF text: {exc}")

    if not text.strip():
        return json_result(success=False, error="No text extracted from PDF (may be scanned/image-only).")

    text = _clean_text(text)
    truncated = len(text) > max_chars
    page_count = text.count("\n\n") + 1

    return json_result(
        success=True, url=url,
        pages=page_count,
        content=text[:max_chars],
        truncated=truncated,
    )


def _read_pdf(args: dict, runtime: dict) -> str:
    """Read a local PDF file and extract its text."""
    raw_path = args.get("path")
    if not raw_path:
        return json_result(success=False, error="path is required")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        return json_result(success=False, error=f"File not found: {path}")
    if path.suffix.lower() != ".pdf":
        return json_result(success=False, error=f"Not a PDF: {path.name}")

    max_chars = int(args.get("max_chars") or 20000)
    text = _extract_pdf_text(path)

    if not text.strip():
        return json_result(success=False, error="No text extracted from PDF (may be scanned/image-only).")

    text = _clean_text(text)
    truncated = len(text) > max_chars
    page_count = text.count("\n\n") + 1

    return json_result(
        success=True, path=str(path),
        pages=page_count,
        content=text[:max_chars],
        truncated=truncated,
    )


# ── Register tools ────────────────────────────────────────────────────────────

registry.register(
    "web_fetch",
    {
        "description": (
            "Fetch a URL and return clean readable text extracted from the page. "
            "Strips navigation, footers, scripts, and other boilerplate — returns only content. "
            "If the URL points to a PDF, automatically extracts text from the PDF instead. "
            "Use this to read professor homepages, lab pages, Google Scholar profiles, "
            "lab group pages, department faculty pages, or any web page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (http:// or https://).",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 8000,
                    "description": "Maximum characters to return. Increase to 15000–20000 for content-rich pages.",
                },
            },
            "required": ["url"],
        },
    },
    _web_fetch,
)

registry.register(
    "read_url_pdf",
    {
        "description": (
            "Download a PDF from a URL and extract its full text content. "
            "Use this for reading research papers, CVs, or any PDF accessible via a direct link. "
            "Supports PyMuPDF (fast), pdfplumber, and PyPDF2 as fallbacks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Direct URL to a PDF file.",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 20000,
                    "description": "Maximum characters to return.",
                },
            },
            "required": ["url"],
        },
    },
    _read_url_pdf,
)

registry.register(
    "read_pdf",
    {
        "description": (
            "Extract text from a local PDF file. "
            "Supports PyMuPDF (fast), pdfplumber, and PyPDF2 as fallbacks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the local PDF file.",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 20000,
                    "description": "Maximum characters to return.",
                },
            },
            "required": ["path"],
        },
    },
    _read_pdf,
)
