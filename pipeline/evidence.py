"""Build one evidence packet per investigation.

A packet is the complete, citable source text handed to the research-card skill:
PSI metadata fields plus one passage per extracted PDF page. Passage ids are
derived from the locator (never from position) so cards stay valid when a packet
is rebuilt. Text is stored exactly as the source has it, including quirks such as
U+FFFD replacement characters; matching is made robust later by normalization.

Why documents are listed separately: a selected PDF that yielded no passages
(not downloaded, unreadable, hash mismatch) must stay visible so a card can state
what it could not examine.
"""
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline import catalog, paths
from pipeline.schema import schema_errors
from pipeline.storage import read_json, write_json_atomic

_METADATA_FIELDS = (
    "title",
    "objective",
    "approach",
    "hypothesis",
    "researchImpacts",
    "description",
    "experimentHardware",
)


class EvidenceError(ValueError):
    """An evidence packet or its inputs are invalid."""


@dataclass(frozen=True)
class BuiltPacket:
    packet: dict[str, Any]
    problems: list[str] = field(default_factory=list)


def _usable(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def metadata_passages(metadata: dict[str, Any], accession: str) -> list[dict[str, Any]]:
    fields: list[tuple[str, Any]] = [(name, metadata.get(name)) for name in _METADATA_FIELDS]
    for index, publication in enumerate(metadata.get("publications") or []):
        title = publication.get("title") if isinstance(publication, dict) else None
        fields.append((f"publications[{index}].title", title))
    return [
        {"id": f"{accession}:meta:{name}", "locator": {"kind": "metadata", "field": name}, "text": value}
        for name, value in fields
        if _usable(value)
    ]


def _extracted_path(extracted_dir: Path, accession: str, entry: dict[str, Any]) -> Path:
    return extracted_dir / accession / f"{entry['file_id']}-v{entry['version']}.json"


def _remote_ref(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "accession": entry["accession"],
        "file_id": entry["file_id"],
        "key": entry["key"],
        "version": entry["version"],
        "filename": entry["filename"],
    }


def _document_passages(entry: dict[str, Any], extracted: dict[str, Any]) -> list[dict[str, Any]]:
    ref = _remote_ref(entry)
    return [
        {
            "id": f"{entry['accession']}:pdf:{entry['file_id']}:v{entry['version']}:p{page['number']}",
            "locator": {"kind": "pdf", **ref, "sha256": entry["sha256"], "page": page["number"]},
            "text": page["text"],
        }
        for page in extracted["pages"]
        if page["text"].strip()
    ]


def _document_entry(
    entry: dict[str, Any], extracted_dir: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    """Return the documents[] record, its passages, and a problem message if any."""
    ref = _remote_ref(entry)
    path = _extracted_path(extracted_dir, entry["accession"], entry)
    if entry["status"] == "failed" or entry["sha256"] is None or not path.is_file():
        record = {**ref, "sha256": entry["sha256"], "status": "not_downloaded", "page_count": None}
        return record, [], None
    extracted = read_json(path)
    if extracted["sha256"] != entry["sha256"]:
        problem = (
            f"{path}: extracted sha256 {extracted['sha256']} differs from manifest {entry['sha256']}; "
            "pages excluded"
        )
        record = {**ref, "sha256": entry["sha256"], "status": "failed", "page_count": extracted["page_count"]}
        return record, [], problem
    record = {**ref, "sha256": entry["sha256"], "status": extracted["status"], "page_count": extracted["page_count"]}
    return record, _document_passages(entry, extracted), None


def build_packet(
    res_dir: Path, accession: str, manifest_files: list[dict[str, Any]], extracted_dir: Path
) -> BuiltPacket:
    metadata = catalog.load_metadata(res_dir, accession)
    passages = metadata_passages(metadata, accession)
    documents: list[dict[str, Any]] = []
    problems: list[str] = []
    pdf_passages = 0
    for entry in manifest_files:
        if entry["accession"] != accession or entry["purpose"] != "evidence" or entry["extension"] != ".pdf":
            continue
        record, found, problem = _document_entry(entry, extracted_dir)
        documents.append(record)
        passages.extend(found)
        pdf_passages += len(found)
        if problem:
            problems.append(problem)
    packet = {
        "investigation": accession,
        "title": str(metadata.get("title") or ""),
        "acronym": str(metadata.get("investigationAcronym") or ""),
        "metadata_version": int(metadata["version"]),
        "source_url": catalog.investigation_url(accession),
        "snapshot_retrieved_at": catalog.snapshot_retrieved_at(res_dir, accession),
        "coverage": "metadata_and_documents" if pdf_passages else "metadata_only",
        "passages": passages,
        "documents": documents,
    }
    errors = schema_errors(packet, "evidence-packet")
    if errors:
        raise EvidenceError(f"{accession}: invalid evidence packet: " + "; ".join(errors))
    return BuiltPacket(packet, problems)


def load_manifest_files(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    errors = schema_errors(manifest, "sample-manifest")
    if errors:
        raise EvidenceError(f"{manifest_path}: invalid sample manifest: " + "; ".join(errors))
    files: list[dict[str, Any]] = manifest["files"]
    return files


def build_all(
    res_dir: Path, manifest_path: Path, extracted_dir: Path, out_dir: Path, accessions: list[str]
) -> list[BuiltPacket]:
    files = load_manifest_files(manifest_path)
    built = []
    for accession in accessions:
        result = build_packet(res_dir, accession, files, extracted_dir)
        write_json_atomic(out_dir / f"{accession}.json", result.packet)
        built.append(result)
    return built


def _status_counts(packet: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for document in packet["documents"]:
        counts[document["status"]] = counts.get(document["status"], 0) + 1
    return ", ".join(f"{status}={count}" for status, count in sorted(counts.items())) or "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.evidence", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write one evidence packet per catalog investigation")
    build.add_argument("--res", type=Path, default=paths.RES)
    build.add_argument("--manifest", type=Path, default=paths.DATA / "sample_manifest.json")
    build.add_argument("--extracted", type=Path, default=paths.EXTRACTED)
    build.add_argument("--out", type=Path, default=paths.DATA / "evidence")
    args = parser.parse_args(argv)
    try:
        accessions = read_json(args.res / "catalog" / "datasets.json")
        built = build_all(args.res, args.manifest, args.extracted, args.out, accessions)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for result in built:
        packet = result.packet
        print(
            f"{packet['investigation']}: {packet['coverage']}, {len(packet['passages'])} passages, "
            f"documents: {_status_counts(packet)}"
        )
        for problem in result.problems:
            print(f"  warning: {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
