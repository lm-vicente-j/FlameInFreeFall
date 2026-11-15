"""Sequential, time-limited PDF text extraction.

Each PDF is handled in its own child process (``pipeline.pdf_worker``) with a
per-file timeout, because pypdf can hang or exhaust memory on malformed input and
only a process can be killed reliably. Files are processed one at a time, in
manifest order, so memory use and results are predictable.

Every PDF yields one "extracted-document" JSON file, including timeouts and
failures (with empty pages), so a failure is explicit data rather than a missing
file. OCR is out of scope: scanned documents end as ``no_text``.
"""
import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.schema import schema_errors
from pipeline.storage import read_json, sha256_file, write_json_atomic

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_WORKER_COMMAND: tuple[str, ...] = (sys.executable, "-m", "pipeline.pdf_worker")
_STDERR_TAIL = 500
_USABLE_STATUSES = ("downloaded", "cached")


class ManifestError(ValueError):
    """The sample manifest is missing, invalid, or unusable for extraction."""


@dataclass(frozen=True)
class DocumentSummary:
    accession: str
    file_id: str
    version: int
    status: str
    page_count: int | None
    characters: int
    error: str | None
    output_path: Path


def _tail(text: str) -> str:
    return text[-_STDERR_TAIL:]


def _failure(status: str, error: str) -> dict[str, Any]:
    """A worker-shaped result for documents the worker could not produce."""
    return {"status": status, "page_count": None, "pages": [], "error": error, "pypdf_version": None}


def _run_worker(command: Sequence[str], pdf: Path, root: Path, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [*command, str(pdf)],
            capture_output=True,
            timeout=timeout_seconds,
            cwd=root,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failure("timeout", f"worker exceeded {timeout_seconds:g} s and was killed")
    stderr_tail = _tail(completed.stderr.decode("utf-8", errors="replace"))
    if completed.returncode != 0:
        return _failure("failed", f"worker exited with code {completed.returncode}: {stderr_tail}")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _failure("failed", f"worker output is not valid JSON ({exc}): {stderr_tail}")
    if not isinstance(result, dict):
        return _failure("failed", f"worker output is not a JSON object: {stderr_tail}")
    return result


def _build_document(entry: dict[str, Any], sha256: str, result: dict[str, Any]) -> dict[str, Any]:
    version = result.get("pypdf_version")
    return {
        "accession": entry["accession"],
        "file_id": entry["file_id"],
        "key": entry["key"],
        "version": entry["version"],
        "sha256": sha256,
        "extractor": {"name": "pypdf", "version": version if isinstance(version, str) else package_version("pypdf")},
        "status": result.get("status"),
        "error": result.get("error"),
        "page_count": result.get("page_count"),
        "pages": result.get("pages"),
    }


def _document_for(entry: dict[str, Any], sha256: str, result: dict[str, Any]) -> dict[str, Any]:
    """Validate the worker's result; a malformed one becomes an explicit failure."""
    document = _build_document(entry, sha256, result)
    problems = schema_errors(document, "extracted-document")
    if not problems:
        return document
    message = "worker result violates schema: " + "; ".join(problems[:3])
    fallback = _build_document(entry, sha256, _failure("failed", message))
    remaining = schema_errors(fallback, "extracted-document")
    if remaining:
        raise ManifestError(f"{entry['file_id']}: cannot build a valid document: {'; '.join(remaining)}")
    return fallback


def _local_pdf(entry: dict[str, Any], root: Path) -> tuple[Path, str]:
    local_path, expected = entry["local_path"], entry["sha256"]
    if not local_path or not expected:
        raise ManifestError(f"{entry['file_id']}: status {entry['status']!r} requires local_path and sha256")
    return root / local_path, expected


def _extract_one(
    entry: dict[str, Any], root: Path, out_dir: Path, timeout_seconds: float, worker_command: Sequence[str]
) -> DocumentSummary:
    pdf, expected = _local_pdf(entry, root)
    if not pdf.is_file():
        result = _failure("failed", f"local file is missing: {entry['local_path']}")
    else:
        actual = sha256_file(pdf)
        if actual != expected:
            result = _failure("failed", f"sha256 mismatch: manifest {expected}, file {actual}")
        else:
            result = _run_worker(worker_command, pdf, root, timeout_seconds)

    document = _document_for(entry, expected, result)
    destination = out_dir / entry["accession"] / f"{entry['file_id']}-v{entry['version']}.json"
    write_json_atomic(destination, document)
    return DocumentSummary(
        accession=entry["accession"],
        file_id=entry["file_id"],
        version=entry["version"],
        status=document["status"],
        page_count=document["page_count"],
        characters=sum(len(page["text"]) for page in document["pages"]),
        error=document["error"],
        output_path=destination,
    )


def extract_all(
    manifest: dict[str, Any],
    root: Path,
    out_dir: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    worker_command: Sequence[str] = DEFAULT_WORKER_COMMAND,
) -> list[DocumentSummary]:
    """Extract every available PDF in manifest order; one document file per PDF."""
    errors = schema_errors(manifest, "sample-manifest")
    if errors:
        raise ManifestError("invalid sample manifest: " + "; ".join(errors[:3]))
    entries = [
        entry
        for entry in manifest["files"]
        if entry["extension"] == ".pdf" and entry["status"] in _USABLE_STATUSES
    ]
    return [_extract_one(entry, root, out_dir, timeout_seconds, worker_command) for entry in entries]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract page text from the sampled PDFs.")
    parser.add_argument("--manifest", type=Path, default=paths.DATA / "sample_manifest.json")
    parser.add_argument("--out", type=Path, default=paths.EXTRACTED)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="seconds per file")
    args = parser.parse_args(argv)

    try:
        manifest = read_json(args.manifest)
        summaries = extract_all(manifest, paths.ROOT, args.out, args.timeout)
    except (OSError, json.JSONDecodeError, ManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for item in summaries:
        pages = "-" if item.page_count is None else str(item.page_count)
        name = f"{item.accession}/{item.file_id}-v{item.version}"
        print(f"{item.status:<9} {name}  pages={pages}  characters={item.characters}")
    counts: dict[str, int] = {}
    for item in summaries:
        counts[item.status] = counts.get(item.status, 0) + 1
    detail = ", ".join(f"{count} {status}" for status, count in sorted(counts.items())) or "nothing to extract"
    print(f"{len(summaries)} PDFs: {detail}")
    return 1 if any(item.status in ("failed", "timeout") or item.error for item in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
