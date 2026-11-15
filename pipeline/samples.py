"""Budgeted download of the curated sample files.

Selection comes from ``data/sample_selection.json``; every entry is checked
against the saved PSI snapshot before any network call, and the run can never
transfer more than ``budget_bytes`` in total (PLAN.md: 250 MB). Archives and
experimental videos are never downloaded, even if listed.

Design notes:
  * The per-file cap is min(declared size, remaining budget), where "remaining"
    counts bytes actually received (including from failed transfers), so a
    server that lies about sizes cannot push the run over budget.
  * A cached file is trusted only if its size and sha256 match what an earlier
    manifest recorded for the same file_id and version; anything else is
    downloaded again.
  * A failed file is recorded and the run continues; the exit code reports it.
"""
import argparse
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import InvalidURL
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode

from pipeline import paths
from pipeline.catalog import RemoteFile, load_files
from pipeline.psi import (
    API,
    ATTEMPTS,
    BudgetExceededError,
    Opener,
    Readable,
    SizeMismatchError,
    UntrustedUrlError,
    default_opener,
    download_to,
    resolve_signed_url,
)
from pipeline.schema import schema_errors
from pipeline.storage import read_json, sha256_file, write_json_atomic

ALLOWED_EXTENSIONS = frozenset({".pdf", ".xlsx", ".xls", ".csv"})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".wmv", ".mpg", ".mpeg", ".m4v", ".webm", ".flv"})

MAX_PDFS = 20
MAX_BUDGET_BYTES = 250_000_000
"""PLAN.md: up to 20 readable PDFs. Human review time, not storage, is the limit."""

TIMEOUT_SECONDS = 120.0

Clock = Callable[[], datetime]


class SelectionError(ValueError):
    """The selection is invalid or cannot be satisfied; lists every problem found."""


@dataclass(frozen=True)
class PlannedItem:
    file: RemoteFile
    purpose: str
    reason: str


def load_selection(path: Path) -> dict[str, Any]:
    selection: dict[str, Any] = read_json(path)
    errors = schema_errors(selection, "sample-selection")
    if errors:
        raise SelectionError(f"{path} is not a valid sample selection:\n  " + "\n  ".join(errors))
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    for entry in selection["files"]:
        identity = (entry["accession"], entry["file_id"])
        if identity in seen:
            duplicates.append(f"{identity[0]} {identity[1]}")
        seen.add(identity)
    if duplicates:
        raise SelectionError(f"{path} lists files more than once: " + ", ".join(duplicates))
    return selection


def _extension_problem(file: RemoteFile) -> str | None:
    if file.extension in ARCHIVE_EXTENSIONS:
        return f"archives are never downloaded ({file.extension})"
    if file.extension in VIDEO_EXTENSIONS:
        return f"experimental videos are never downloaded ({file.extension})"
    if file.extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        shown = file.extension or "(none)"
        return f"extension {shown} is not in the allowlist ({allowed})"
    return None


def _file_problems(entry: dict[str, Any], remote: RemoteFile | None) -> list[str]:
    if remote is None:
        return ["file_id not found in the saved PSI snapshot"]
    problems: list[str] = []
    if remote.key != entry["key"]:
        problems.append(f"key differs from snapshot ({remote.key})")
    if remote.version != entry["version"]:
        problems.append(f"version {entry['version']} differs from snapshot version {remote.version}")
    if remote.bytes is None:
        problems.append("snapshot has no byte size")
    if remote.access != "public":
        problems.append(f"file is {remote.access}")
    extension_problem = _extension_problem(remote)
    if extension_problem:
        problems.append(extension_problem)
    return problems


def plan(selection: dict[str, Any], res_dir: Path) -> list[PlannedItem]:
    """Check every entry against the snapshot; raise one error listing all problems."""
    if not 0 < selection["budget_bytes"] <= MAX_BUDGET_BYTES:
        raise SelectionError("The total sample budget must be between 1 and 250000000 bytes")
    snapshots: dict[str, dict[str, RemoteFile]] = {}
    items: list[PlannedItem] = []
    problems: list[str] = []
    local_paths: dict[tuple[str, str], str] = {}
    for entry in selection["files"]:
        accession = entry["accession"]
        label = f"{accession} {entry['file_id']}"
        if accession not in snapshots:
            snapshots[accession] = {f.file_id: f for f in load_files(res_dir, accession)}
        remote = snapshots[accession].get(entry["file_id"])
        found = _file_problems(entry, remote)
        problems.extend(f"{label}: {problem}" for problem in found)
        if remote is None or found:
            continue
        slot = (accession, remote.filename)
        if slot in local_paths:
            problems.append(f"{label}: filename {remote.filename} collides with {local_paths[slot]}")
            continue
        local_paths[slot] = label
        items.append(PlannedItem(remote, entry["purpose"], entry["reason"]))
    pdfs = sum(1 for entry in selection["files"] if entry["key"].lower().endswith(".pdf"))
    if pdfs > MAX_PDFS:
        problems.append(f"selection lists {pdfs} PDFs; the limit is {MAX_PDFS}")
    if problems:
        raise SelectionError("Selection rejected:\n  " + "\n  ".join(problems))
    declared = sum(item.file.bytes or 0 for item in items)
    if declared > selection["budget_bytes"]:
        raise SelectionError(
            f"Selection rejected: declared size {declared} bytes exceeds the budget of "
            f"{selection['budget_bytes']} bytes"
        )
    return items


class _CountingResponse:
    def __init__(self, inner: Readable, counter: list[int], allowance: int, deadline: float) -> None:
        self._inner = inner
        self._counter = counter
        self._allowance = allowance
        self._deadline = deadline

    def read(self, size: int = -1, /) -> bytes:
        remaining = self._allowance - self._counter[0]
        seconds = self._deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("The overall file-download deadline expired")
        if remaining <= 0:
            raise BudgetExceededError("The cumulative sample download budget is exhausted")
        raw = getattr(getattr(self._inner, "fp", None), "raw", None)
        socket = getattr(raw, "_sock", None)
        if socket is not None:
            socket.settimeout(seconds)
        chunk = self._inner.read(min(size if size >= 0 else remaining, remaining))
        self._counter[0] += len(chunk)
        if time.monotonic() > self._deadline:
            raise TimeoutError("The overall file-download deadline expired")
        return chunk


class _CountingContext:
    def __init__(
        self, inner: AbstractContextManager[Readable], counter: list[int], allowance: int, deadline: float
    ) -> None:
        self._inner = inner
        self._counter = counter
        self._allowance = allowance
        self._deadline = deadline

    def __enter__(self) -> _CountingResponse:
        return _CountingResponse(self._inner.__enter__(), self._counter, self._allowance, self._deadline)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._inner.__exit__(exc_type, exc, traceback)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _previous_records(previous: dict[str, Any] | None) -> dict[tuple[str, int], dict[str, Any]]:
    if previous is None:
        return {}
    return {
        (record["file_id"], record["version"]): record
        for record in previous["files"]
        if record["status"] != "failed" and record["sha256"] is not None
    }


def _record(
    item: PlannedItem,
    status: str,
    sha256: str | None,
    local_path: str | None,
    retrieved_at: str | None,
    error: str | None,
) -> dict[str, Any]:
    file = item.file
    return {
        "accession": file.accession,
        "file_id": file.file_id,
        "key": file.key,
        "version": file.version,
        "filename": file.filename,
        "category": file.category,
        "extension": file.extension,
        "bytes": file.bytes,
        "access": file.access,
        "purpose": item.purpose,
        "status": status,
        "sha256": sha256,
        "local_path": local_path,
        "retrieved_at": retrieved_at,
        "error": error,
        "source_url": f"{API}/{file.accession}/download?" + urlencode(
            {"file": file.filename, "version": file.version, "redirect": "false"}
        ),
        "investigation_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{file.accession}",
    }


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _cached_digest(old: dict[str, Any] | None, destination: Path, declared: int) -> str | None:
    """Return the file's hash if it is a trustworthy copy of the recorded download."""
    if old is None or not destination.is_file() or destination.stat().st_size != declared:
        return None
    digest = sha256_file(destination)
    return digest if digest == old["sha256"] else None


def run(
    selection: dict[str, Any],
    res_dir: Path,
    samples_dir: Path,
    root: Path,
    previous_manifest: dict[str, Any] | None,
    opener: Opener,
    now: Clock,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    items = plan(selection, res_dir)
    budget: int = selection["budget_bytes"]
    previous = _previous_records(previous_manifest)
    cumulative = 0 if previous_manifest is None else previous_manifest.get(
        "cumulative_transferred_bytes", previous_manifest["transferred_bytes"]
    )
    history_complete = previous_manifest is None or previous_manifest.get(
        "budget_history_complete", "cumulative_transferred_bytes" in previous_manifest
    )
    if cumulative > budget:
        raise SelectionError("The new budget is below the transfer total already recorded")
    transferred = 0
    records: list[dict[str, Any]] = []
    for item in items:
        file = item.file
        declared = file.bytes or 0
        destination = samples_dir / file.accession / file.filename
        local_path = _relative(destination, root)
        old = previous.get((file.file_id, file.version))
        cached = _cached_digest(old, destination, declared)
        if old is not None and cached is not None:
            when = old["retrieved_at"] or _timestamp(now())
            records.append(_record(item, "cached", cached, local_path, when, None))
            continue
        remaining = budget - cumulative - transferred if history_complete else 0
        counter = [0]
        deadline = time.monotonic() + timeout

        def counting(
            target: str, seconds: float, _counter: list[int] = counter,
            _remaining: int = remaining, _deadline: float = deadline,
        ) -> _CountingContext:
            left = _deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("The overall file-download deadline expired")
            return _CountingContext(opener(target, min(seconds, left)), _counter, _remaining, _deadline)

        try:
            if declared > remaining:
                raise BudgetExceededError(
                    f"{file.filename}: {declared} declared bytes exceed the {remaining} bytes left in the budget"
                )
            url = resolve_signed_url(file.accession, file.filename, file.version, counting, timeout, sleep)
            for attempt in range(ATTEMPTS):
                try:
                    allowance = remaining - counter[0]
                    if declared > allowance:
                        raise BudgetExceededError("Insufficient cumulative budget after API responses or retries")
                    _, digest = download_to(url, destination, declared, allowance, counting, timeout)
                    break
                except (OSError, SizeMismatchError) as error:
                    if (isinstance(error, HTTPError) and 400 <= error.code < 500) or attempt == ATTEMPTS - 1:
                        raise
                    sleep(min(2**attempt, max(0, deadline - time.monotonic())))
            records.append(_record(item, "downloaded", digest, local_path, _timestamp(now()), None))
        except (OSError, InvalidURL, UnicodeError, UntrustedUrlError, BudgetExceededError, SizeMismatchError) as error:
            records.append(_record(item, "failed", None, None, None, f"{type(error).__name__}: {error}"))
        transferred += counter[0]
    manifest = {
        "generated_at": _timestamp(now()),
        "budget_bytes": budget,
        "transferred_bytes": transferred,
        "cumulative_transferred_bytes": cumulative + transferred,
        "budget_history_complete": history_complete,
        "snapshots": [
            {
                "accession": accession,
                "metadata_version": read_json(res_dir / accession / "metadata.json")["version"],
                "retrieved_at": read_json(res_dir / accession / "provenance.json")[0]["retrieved_at"],
                "metadata_sha256": sha256_file(res_dir / accession / "metadata.json"),
                "files_sha256": sha256_file(res_dir / accession / "files.json"),
            }
            for accession in sorted({item.file.accession for item in items})
        ],
        "files": records,
    }
    errors = schema_errors(manifest, "sample-manifest")
    if errors:
        raise ValueError("Refusing to return an invalid sample manifest:\n  " + "\n  ".join(errors))
    return manifest


def _megabytes(count: int) -> str:
    return f"{count / 1e6:,.2f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the curated sample files within the byte budget.")
    parser.add_argument("--selection", type=Path, default=paths.DATA / "sample_selection.json")
    parser.add_argument("--res", type=Path, default=paths.RES)
    parser.add_argument("--samples", type=Path, default=paths.SAMPLES)
    parser.add_argument("--manifest", type=Path, default=paths.DATA / "sample_manifest.json")
    parser.add_argument("--dry-run", action="store_true", help="validate and print the plan; no network")
    args = parser.parse_args(argv)
    try:
        selection = load_selection(args.selection)
        items = plan(selection, args.res)
        if args.dry_run:
            for item in items:
                print(f"{item.file.accession}\t{item.file.bytes:>10} B\t{item.file.filename}")
            total = sum(item.file.bytes or 0 for item in items)
            print(f"Plan: {len(items)} files, {_megabytes(total)} of {_megabytes(selection['budget_bytes'])} budget")
            return 0
        previous = read_json(args.manifest) if args.manifest.is_file() else None
        if previous is not None and schema_errors(previous, "sample-manifest"):
            raise SelectionError("Existing manifest is invalid; refusing to reset its cumulative budget")
        manifest = run(
            selection, args.res, args.samples, paths.ROOT, previous, default_opener,
            lambda: datetime.now(UTC),
        )
    except (SelectionError, FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    write_json_atomic(args.manifest, manifest)
    failed = 0
    for record in manifest["files"]:
        suffix = f"\t{record['error']}" if record["error"] else ""
        print(f"{record['status']:<11}{record['accession']}\t{record['filename']}{suffix}")
        failed += record["status"] == "failed"
    print(
        f"{len(manifest['files']) - failed} ok, {failed} failed; transferred "
        f"{_megabytes(manifest['transferred_bytes'])} of {_megabytes(manifest['budget_bytes'])} budget"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
