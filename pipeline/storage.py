"""Hashing and crash-safe JSON persistence."""
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Replace ``path`` only after the complete new content is on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def dump_json(value: Any) -> str:
    """Serialize deterministically so regenerated files produce minimal diffs."""
    rendered = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    return rendered.encode("utf-8", errors="backslashreplace").decode("utf-8")


def write_json_atomic(path: Path, value: Any) -> None:
    write_bytes_atomic(path, dump_json(value).encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
