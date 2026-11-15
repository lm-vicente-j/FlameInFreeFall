"""Child-process PDF text extractor: ``python -m pipeline.pdf_worker <pdf>``.

Why a separate process: pypdf can hang or exhaust memory on malformed files, and
a thread cannot be killed while a child process can. The parent
(``pipeline.pdf_extract``) enforces the time limit.

Writes exactly one JSON object to stdout (UTF-8, whatever the console code page)
and exits 0 whenever that object was written. Page text is kept exactly as pypdf
returns it because downstream citation matching depends on the exact characters.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pypdf


def _result(
    status: str,
    page_count: int | None,
    pages: list[dict[str, Any]],
    error: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "page_count": page_count,
        "pages": pages,
        "error": error,
        "pypdf_version": pypdf.__version__,
    }


def _failed(message: str) -> dict[str, Any]:
    return _result("failed", None, [], message)


def extract(path: Path) -> dict[str, Any]:
    """Extract page texts; never raises for document-level problems."""
    try:
        reader = pypdf.PdfReader(str(path), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return _failed("encrypted: the empty password was rejected")
        page_total = len(reader.pages)
    except Exception as exc:
        return _failed(f"{type(exc).__name__}: {exc}")

    pages: list[dict[str, Any]] = []
    page_errors: list[str] = []
    for index in range(page_total):
        number = index + 1
        try:
            text = reader.pages[index].extract_text()
        except Exception as exc:
            text = ""
            page_errors.append(f"page {number}: {type(exc).__name__}: {exc}")
        pages.append({"number": number, "text": text})

    error = "; ".join(page_errors) if page_errors else None
    has_text = any(page["text"].strip() for page in pages)
    return _result("extracted" if has_text else "no_text", page_total, pages, error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract page text from one PDF as JSON on stdout.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args(argv)
    # ASCII-escaped JSON is safe on any pipe and round-trips lone surrogates exactly.
    payload = json.dumps(extract(args.pdf), ensure_ascii=True)
    sys.stdout.buffer.write(payload.encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
