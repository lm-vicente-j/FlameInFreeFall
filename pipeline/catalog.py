"""Read the saved PSI metadata snapshot (``res/<accession>/``).

The snapshot is produced by ``scripts/download_metadata.py``. Everything here is
offline: selecting files for download must be reproducible from saved metadata,
not from whatever PSI happens to serve today.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pipeline.storage import read_json
from scripts.download_metadata import flatten_files

Access = Literal["public", "restricted", "hidden"]

_INVESTIGATION_URL = "https://psi.nasa.gov/physci/repo/data/investigations/"


class SnapshotMissingError(FileNotFoundError):
    """The saved PSI metadata for an accession is absent."""


@dataclass(frozen=True)
class RemoteFile:
    accession: str
    file_id: str
    key: str
    version: int
    bytes: int | None
    category: str | None
    subcategory: str | None
    restricted: bool
    visible: bool

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        dot = self.filename.rfind(".")
        return self.filename[dot:].lower() if dot > 0 else ""

    @property
    def access(self) -> Access:
        if self.restricted:
            return "restricted"
        if not self.visible:
            return "hidden"
        return "public"


def _snapshot_file(res_dir: Path, accession: str, name: str) -> Path:
    path = res_dir / accession / name
    if not path.is_file():
        raise SnapshotMissingError(
            f"Saved PSI snapshot is missing {path}. Run scripts/download_metadata.py first."
        )
    return path


def load_files(res_dir: Path, accession: str) -> list[RemoteFile]:
    listing = read_json(_snapshot_file(res_dir, accession, "files.json"))
    return [
        RemoteFile(
            accession=accession,
            file_id=str(item["id"]),
            key=item["key"],
            version=int(item["version"]),
            bytes=item["bytes"],
            category=item["category"],
            subcategory=item["subcategory"],
            restricted=bool(item["restricted"]),
            visible=bool(item["visible"]),
        )
        for item in flatten_files(listing)  # type: ignore[no-untyped-call]
    ]


def load_metadata(res_dir: Path, accession: str) -> dict[str, Any]:
    metadata: dict[str, Any] = read_json(_snapshot_file(res_dir, accession, "metadata.json"))
    return metadata


def snapshot_retrieved_at(res_dir: Path, accession: str) -> str:
    provenance = read_json(_snapshot_file(res_dir, accession, "provenance.json"))
    return str(provenance[0]["retrieved_at"])


def investigation_url(accession: str) -> str:
    return _INVESTIGATION_URL + accession
