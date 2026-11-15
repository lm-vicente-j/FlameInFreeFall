"""Validated offline SQLite catalog and literal scientific search."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.cards import statements, validate
from pipeline.schema import FORMATS, schema_errors
from scripts.download_metadata import flatten_files

_BUILD_LOCK = threading.Lock()
_TABLES = ("investigations", "cards", "evidence", "remote_files")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
 accession TEXT PRIMARY KEY, metadata_version INTEGER NOT NULL,
 snapshot_retrieved_at TEXT NOT NULL, metadata_sha256 TEXT NOT NULL,
 source_url TEXT NOT NULL, fingerprint TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (
 accession TEXT PRIMARY KEY REFERENCES investigations(accession),
 source_version INTEGER NOT NULL, fingerprint TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, investigation TEXT NOT NULL REFERENCES investigations(accession),
 passage_id TEXT NOT NULL, excerpt TEXT NOT NULL, source_url TEXT NOT NULL,
 locator_json TEXT NOT NULL, fingerprint TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remote_files (
 accession TEXT NOT NULL REFERENCES investigations(accession), file_id TEXT NOT NULL,
 version INTEGER NOT NULL, key TEXT NOT NULL, filename TEXT NOT NULL,
 filename_fold TEXT NOT NULL, category TEXT, category_fold TEXT, extension TEXT NOT NULL,
 bytes INTEGER, access TEXT NOT NULL, download_sha256 TEXT,
 fingerprint TEXT NOT NULL, record_json TEXT NOT NULL, source_json TEXT NOT NULL,
 PRIMARY KEY (accession, file_id, version));
CREATE VIRTUAL TABLE IF NOT EXISTS scientific_search USING fts5(
 accession UNINDEXED, title, acronym, content, tokenize='unicode61');
"""


class CatalogError(ValueError):
    """Prepared inputs or an active catalog failed validation."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _timestamp(value: str) -> datetime:
    FORMATS.check(value, "date-time")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _verify_source(directory: Path, name: str, provenance: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [entry for entry in provenance if entry.get("file") == name]
    if len(entries) != 1:
        raise CatalogError(f"{directory.name}: expected one provenance entry for {name}")
    entry = entries[0]
    raw = (directory / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"] or len(raw) != entry["response_bytes"]:
        raise CatalogError(f"{directory.name}/{name}: source bytes differ from provenance")
    _timestamp(entry["retrieved_at"])
    FORMATS.check(entry["url"], "uri")
    return entry


def _download_hashes(data_dir: Path) -> dict[tuple[str, str, int], str]:
    """Only attach manifest hashes when downloaded bytes are still verifiable."""
    result: dict[tuple[str, str, int], str] = {}
    manifest = data_dir / "sample_manifest.json"
    if not manifest.is_file():
        return result
    for item in _read(manifest).get("files", []):
        if not item.get("sha256") or not item.get("local_path"):
            continue
        path = (data_dir.parent / item["local_path"]).resolve()
        if not path.is_relative_to(data_dir.parent.resolve()):
            raise CatalogError("Downloaded sample path escapes the project")
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise CatalogError(f"Downloaded sample hash differs: {item['local_path']}")
        identity = (item["accession"], str(item["file_id"]), item["version"])
        if identity in result and result[identity] != digest:
            raise CatalogError("Conflicting downloaded hashes for one remote identity")
        result[identity] = digest
    return result


def _prepared(
    data_dir: Path, res_dir: Path, allow_pending: bool
) -> list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]]:
    hashes = _download_hashes(data_dir)
    prepared = []
    seen: set[str] = set()
    for card_path in sorted((data_dir / "cards").glob("*.json")):
        card = _read(card_path)
        problems = schema_errors(card, "research-card")
        if problems:
            raise CatalogError(f"{card_path}: {'; '.join(problems)}")
        accession = card["accession"]
        if accession in seen:
            raise CatalogError(f"Duplicate card accession: {accession}")
        seen.add(accession)
        packet = _read(data_dir / "evidence" / f"{accession}.json")
        problems = schema_errors(packet, "evidence-packet")
        if not problems:
            problems = validate(card, packet)
        if problems:
            raise CatalogError(f"{accession}: {'; '.join(problems)}")
        status = card["review"]["status"]
        if status == "rejected" or (not allow_pending and status != "approved"):
            raise CatalogError(f"{accession}: review status {status} is not permitted")
        directory = res_dir / accession
        provenance = _read(directory / "provenance.json")
        source = _verify_source(directory, "metadata.json", provenance)
        file_source = _verify_source(directory, "files.json", provenance)
        metadata = _read(directory / "metadata.json")
        version = metadata.get("version")
        if type(version) is not int or version < 1 or version != card["source_version"]:
            raise CatalogError(f"{accession}: metadata and card versions differ")
        if metadata.get("accession", accession) != accession:
            raise CatalogError(f"{accession}: metadata accession differs")
        if packet["title"] != metadata.get("title") or packet["acronym"] != (
            metadata.get("investigationAcronym") or ""
        ):
            raise CatalogError(f"{accession}: packet title or acronym differs from saved metadata")
        for passage in packet["passages"]:
            locator = passage["locator"]
            if locator["kind"] != "metadata":
                continue
            field = locator["field"]
            publication = re.fullmatch(r"publications\[(\d+)\]\.title", field)
            if publication:
                index = int(publication[1])
                publications = metadata.get("publications") or []
                value = publications[index].get("title") if index < len(publications) else None
            else:
                value = metadata.get(field)
            if passage["text"] != value:
                raise CatalogError(f"{accession}: metadata passage {field} differs from saved source")
        oldest = min(
            _timestamp(item)
            for item in (source["retrieved_at"], file_source["retrieved_at"], packet["snapshot_retrieved_at"])
        )
        investigation = {
            "accession": accession,
            "metadata_version": version,
            "snapshot_retrieved_at": oldest.isoformat(),
            "metadata_sha256": source["sha256"],
            "source_url": packet["source_url"],
            "metadata_path": str(directory / "metadata.json"),
            "scientific_metadata": metadata,
            "provenance": provenance,
            "evidence_packet": packet,
        }
        files = []
        identities: set[tuple[str, int]] = set()
        for raw in flatten_files(_read(directory / "files.json")):
            file_id, file_version = str(raw["id"]), raw["version"]
            if (
                not isinstance(raw["key"], str)
                or re.findall(r"(?:^|/)(PSI-\d+)(?=/)", raw["key"]) != [accession]
                or type(file_version) is not int
                or file_version < 1
                or not file_id
            ):
                raise CatalogError(f"{accession}: invalid remote-file identity")
            if (file_id, file_version) in identities:
                raise CatalogError(f"{accession}: duplicate remote-file identity")
            identities.add((file_id, file_version))
            size = raw["bytes"]
            if size is not None and (type(size) is not int or size < 0):
                raise CatalogError(f"{accession}: invalid remote-file byte count")
            if type(raw["visible"]) is not bool or type(raw["restricted"]) is not bool:
                raise CatalogError(f"{accession}: invalid remote-file access flags")
            filename = raw["key"].rsplit("/", 1)[-1]
            dot = filename.rfind(".")
            record = {
                "accession": accession,
                "file_id": file_id,
                "version": file_version,
                "key": raw["key"],
                "filename": filename,
                "category": raw["category"],
                "extension": filename[dot:].lower() if dot > 0 else "",
                "bytes": size,
                "access": "hidden" if not raw["visible"] else "restricted" if raw["restricted"] else "public",
                "download_sha256": hashes.get((accession, file_id, file_version)),
                "_source": raw,
            }
            files.append(record)
        keys = {item["key"] for item in files}
        by_identity = {(item["file_id"], item["version"]): item for item in files}
        references = [*packet["documents"], *packet["tables"]]
        references.extend(item["locator"] for item in packet["passages"] if item["locator"]["kind"] != "metadata")
        for reference in references:
            remote = by_identity.get((reference["file_id"], reference["version"]))
            if remote is None or any(reference[key] != remote[key] for key in ("accession", "key", "filename")):
                raise CatalogError(f"{accession}: document reference differs from the supplied file catalog")
            if remote["download_sha256"] and reference.get("sha256") != remote["download_sha256"]:
                raise CatalogError(f"{accession}: document hash differs from verified downloaded bytes")
        for resource in card["modeling_resources"]:
            if not set(resource["file_keys"]).issubset(keys):
                raise CatalogError(f"{accession}: modeling resource is absent from supplied inventory")
        prepared.append((investigation, card, files))
    if not prepared:
        raise CatalogError("No prepared research cards found")
    return prepared


def _search_content(card: dict[str, Any]) -> str:
    texts = [text for _, text, ids in statements(card) if ids]
    texts.extend(item["excerpt"] for item in card["evidence"])
    return "\n".join(texts)


def _validate_database(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CatalogError("Candidate contains broken foreign keys")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise CatalogError("Candidate failed SQLite integrity check")
    counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in _TABLES}
    indexed = connection.execute("SELECT count(*) FROM scientific_search").fetchone()[0]
    if indexed != counts["cards"]:
        raise CatalogError("Search index count differs from current cards")
    connection.execute(
        "SELECT accession FROM scientific_search WHERE scientific_search MATCH ?", ('"catalogprobe"',)
    ).fetchall()
    evidence = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT id, record_json FROM evidence")}
    for row in connection.execute("SELECT accession, record_json FROM cards"):
        card = json.loads(row[1])
        for item in card["evidence"]:
            if evidence.get(item["id"]) != item:
                raise CatalogError(f"{row[0]}: evidence body is missing or differs")
    return counts


def _upsert(
    connection: sqlite3.Connection, investigation: dict[str, Any], card: dict[str, Any], files: list[dict[str, Any]]
) -> None:
    accession = investigation["accession"]
    old = connection.execute("SELECT metadata_version FROM investigations WHERE accession=?", (accession,)).fetchone()
    if old and old[0] > investigation["metadata_version"]:
        raise CatalogError(f"{accession}: refusing older metadata version")
    connection.execute(
        "INSERT OR REPLACE INTO investigations VALUES (?,?,?,?,?,?,?)",
        (
            accession,
            investigation["metadata_version"],
            investigation["snapshot_retrieved_at"],
            investigation["metadata_sha256"],
            investigation["source_url"],
            _fingerprint(investigation),
            _json(investigation),
        ),
    )
    connection.execute(
        "INSERT OR REPLACE INTO cards VALUES (?,?,?,?)",
        (accession, card["source_version"], _fingerprint(card), _json(card)),
    )
    for item in card["evidence"]:
        old = connection.execute("SELECT fingerprint FROM evidence WHERE id=?", (item["id"],)).fetchone()
        if old and old[0] != _fingerprint(item):
            raise CatalogError(f"Evidence ID collision: {item['id']}")
        connection.execute(
            "INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?)",
            (
                item["id"],
                item["investigation"],
                item["passage_id"],
                item["excerpt"],
                item["source_url"],
                _json(item["locator"]),
                _fingerprint(item),
                _json(item),
            ),
        )
    for item in files:
        source = item["_source"]
        item = {key: value for key, value in item.items() if key != "_source"}
        old = connection.execute(
            "SELECT download_sha256 FROM remote_files WHERE accession=? AND file_id=? AND version=?",
            (accession, item["file_id"], item["version"]),
        ).fetchone()
        if old and old[0]:
            if item["download_sha256"] and old[0] != item["download_sha256"]:
                raise CatalogError(f"Downloaded bytes changed for {item['key']}")
            item["download_sha256"] = old[0]
        connection.execute(
            "INSERT OR REPLACE INTO remote_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                accession,
                item["file_id"],
                item["version"],
                item["key"],
                item["filename"],
                item["filename"].casefold(),
                item["category"],
                item["category"].casefold() if item["category"] is not None else None,
                item["extension"],
                item["bytes"],
                item["access"],
                item["download_sha256"],
                _fingerprint(item),
                _json(item),
                _json(source),
            ),
        )


def build_catalog(db_path: Path, data_dir: Path, res_dir: Path, allow_pending: bool = True) -> dict[str, Any]:
    """Validate a subset import and atomically replace the active generation.

    Absent existing studies and file versions are retained. Pending review is
    allowed for development only; validation never promotes scientific review.
    """
    db_path, data_dir, res_dir = Path(db_path), Path(data_dir), Path(res_dir)
    candidate: Path | None = None
    previous: Path | None = None
    with _BUILD_LOCK:
        try:
            prepared = _prepared(data_dir, res_dir, allow_pending)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=db_path.name + ".candidate-", dir=db_path.parent)
            os.close(descriptor)
            candidate = Path(name)
            connection = sqlite3.connect(candidate)
            try:
                if db_path.is_file():
                    with closing(_connect(db_path)) as active:
                        active.backup(connection)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript(_SCHEMA)
                with connection:
                    for investigation, card, files in prepared:
                        _upsert(connection, investigation, card, files)
                    connection.execute("DELETE FROM scientific_search")
                    for (raw,) in connection.execute("SELECT record_json FROM cards").fetchall():
                        card = json.loads(raw)
                        connection.execute(
                            "INSERT INTO scientific_search VALUES (?,?,?,?)",
                            (card["accession"], card["title"], card["acronym"], _search_content(card)),
                        )
                    counts = _validate_database(connection)
            finally:
                connection.close()
            if db_path.is_file():
                descriptor, name = tempfile.mkstemp(prefix=db_path.name + ".previous-", dir=db_path.parent)
                os.close(descriptor)
                previous = Path(name)
                with closing(_connect(db_path)) as active:
                    backup = sqlite3.connect(previous)
                    try:
                        active.backup(backup)
                    finally:
                        backup.close()
            os.replace(candidate, db_path)
            candidate = None
            try:
                health = Catalog(db_path).health()
            except Exception:
                if previous is not None:
                    os.replace(previous, db_path)
                    previous = None
                else:
                    db_path.unlink(missing_ok=True)
                raise
            return {**health, **counts}
        except CatalogError:
            raise
        except Exception as error:
            raise CatalogError(f"Catalog build failed: {error}") from error
        finally:
            if candidate is not None:
                candidate.unlink(missing_ok=True)
            if previous is not None:
                previous.unlink(missing_ok=True)


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be nonnegative integers")


def _synonyms(query: str) -> list[list[str]]:
    words = [term.casefold() for term in query.split()]
    path = Path(__file__).resolve().parents[1] / "data" / "search_synonyms.json"
    if not path.is_file():
        return [[word] for word in words]
    aliases: list[tuple[list[str], list[str]]] = []
    for entry in _read(path).get("entries", []):
        if entry.get("review", {}).get("status") != "approved":
            continue
        terms = [term.casefold() for term in entry["terms"]]
        aliases.extend((term.split(), terms) for term in terms)
    aliases.sort(key=lambda item: -len(item[0]))
    groups: list[list[str]] = []
    index = 0
    while index < len(words):
        for phrase, terms in aliases:
            if words[index : index + len(phrase)] == phrase:
                groups.append(terms)
                index += len(phrase)
                break
        else:
            groups.append([words[index]])
            index += 1
    return groups


class Catalog:
    """Read one validated database generation per operation, without creating it."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._checked().close()

    def _checked(self) -> sqlite3.Connection:
        connection = None
        try:
            connection = _connect(self.db_path)
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
            if not set(_TABLES).union({"scientific_search"}).issubset(names):
                connection.close()
                raise CatalogError("Catalog schema is unavailable")
            return connection
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise CatalogError("Catalog is unavailable") from error

    def health(self) -> dict[str, Any]:
        connection = self._checked()
        try:
            dates = [
                _timestamp(row[0]) for row in connection.execute("SELECT snapshot_retrieved_at FROM investigations")
            ]
            return {
                "snapshot_date": min(dates).date().isoformat() if dates else None,
                "investigation_count": len(dates),
            }
        finally:
            connection.close()

    def study(self, accession: str) -> dict[str, Any] | None:
        return self._record("cards", "accession", accession)

    def evidence(self, id: str) -> dict[str, Any] | None:
        return self._record("evidence", "id", id)

    def _record(self, table: str, key: str, value: str) -> dict[str, Any] | None:
        connection = self._checked()
        try:
            row = connection.execute(f"SELECT record_json FROM {table} WHERE {key}=?", (value,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            connection.close()

    def studies(
        self, q: str = "", safety_category: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        _page(limit, offset)
        if not isinstance(q, str) or len(q.strip()) > 200:
            raise ValueError("q must be text of at most 200 characters")
        if safety_category not in (None, "prevention", "detection", "suppression"):
            raise ValueError("Unsupported safety_category")
        query = q.strip()
        groups = _synonyms(query)
        connection = self._checked()
        try:
            scores = {}
            if query:
                searchable = [group for group in groups if all(any(char.isalnum() for char in term) for term in group)]
                expression = " AND ".join(
                    "(" + " OR ".join('"' + term.replace('"', '""') + '"' for term in group) + ")"
                    for group in searchable
                )
                if expression:
                    scores = {
                        row[0]: -row[1]
                        for row in connection.execute(
                            "SELECT accession, bm25(scientific_search,0,10,15,1) "
                            "FROM scientific_search WHERE scientific_search MATCH ?",
                            (expression,),
                        )
                    }
            results = []
            for row in connection.execute("SELECT accession, record_json FROM cards"):
                card = json.loads(row[1])
                if safety_category and not any(
                    item["category"] == safety_category and item["evidence_ids"] for item in card["safety_categories"]
                ):
                    continue
                content = "\n".join((card["title"], card["acronym"] or "", _search_content(card))).casefold()
                if query and not all(any(term in content for term in group) for group in groups):
                    continue
                results.append((card, scores.get(card["accession"], 0.0)))
            # Ties follow the HTTP accession order; unsearched pages use numeric IDs.
            results.sort(
                key=(lambda item: (-item[1], item[0]["accession"]))
                if query
                else (lambda item: int(item[0]["accession"].split("-")[1]))
            )
            selected = results[offset : offset + limit]
            matches = []
            if query:
                for rank, (card, score) in enumerate(selected, start=offset + 1):
                    excerpts = [
                        item
                        for item in card["evidence"]
                        if any(term in item["excerpt"].casefold() for group in groups for term in group)
                    ]
                    matches.append({"accession": card["accession"], "rank": rank, "score": score, "evidence": excerpts})
            return [item[0] for item in selected], {
                "total": len(results),
                "limit": limit,
                "offset": offset,
                "query": query,
                "safety_category": safety_category,
                "matches": matches,
            }
        finally:
            connection.close()

    def files(
        self,
        accession: str,
        filename: str = "",
        category: str | None = None,
        extension: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        _page(limit, offset)
        if not isinstance(filename, str) or (category is not None and not isinstance(category, str)):
            raise ValueError("Filename and category must be text")
        if extension is not None and (not isinstance(extension, str) or not re.fullmatch(r"\.[^\s./\\]+", extension)):
            raise ValueError("Extension must begin with a dot")
        connection = self._checked()
        try:
            if connection.execute("SELECT 1 FROM investigations WHERE accession=?", (accession,)).fetchone() is None:
                raise KeyError(accession)
            where, parameters = ["accession=?", "instr(filename_fold,?)>0"], [accession, filename.casefold()]
            if category is not None:
                where.append("category_fold=?")
                parameters.append(category.casefold())
            if extension is not None:
                where.append("extension=?")
                parameters.append(extension.lower())
            clause = " AND ".join(where)
            total = connection.execute("SELECT count(*) FROM remote_files WHERE " + clause, parameters).fetchone()[0]
            rows = connection.execute(
                "SELECT record_json FROM remote_files WHERE "
                + clause
                + " ORDER BY filename_fold, filename, file_id, version LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            return [json.loads(row[0]) for row in rows], {
                "total": total,
                "limit": limit,
                "offset": offset,
                "accession": accession,
                "filename": filename,
                "category": category,
                "extension": extension.lower() if extension else None,
            }
        finally:
            connection.close()
