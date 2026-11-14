#!/usr/bin/env python3
"""Save raw NASA PSI metadata and generate combustion research inventories.

"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = "https://psi.nasa.gov"
API = BASE + "/geode-py/ws"


def write_bytes(path, content):
    """Replace a file only after its complete contents have been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def fetch_json(url, destination, provenance, timeout, payload=None):
    """Validate JSON, then save the response body without reformatting it."""
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Accept": "application/json", "User-Agent": "FlameInFreeFall-Metadata/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=body, headers=headers), timeout=timeout) as response:
                raw = response.read()
            value = json.loads(raw)
            write_bytes(destination, raw)
            provenance.append({
                "url": url,
                "method": "GET" if body is None else "POST",
                "request_body": payload,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "response_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "file": destination.name,
            })
            return value
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def byte_count(value):
    """Accept PSI's integer, float, or string sizes without inventing missing sizes."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError(f"Invalid byte count: {value!r}")
        return int(number)
    except InvalidOperation as error:
        raise ValueError(f"Invalid byte count: {value!r}") from error


def size_label(value):
    if value is None:
        return "Not reported"
    for unit, divisor in (("TB", 10**12), ("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if value >= divisor:
            return f"{value / divisor:,.2f} {unit}"
    return f"{value:,} B"


def cell(value):
    """Escape source text for a Markdown table without summarizing it."""
    return " ".join(str(value if value not in (None, "") else "Not reported").split()).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def flatten_files(response):
    """Use the current file listing, not metadata's historical added/removed lists."""
    if not isinstance(response, dict) or not isinstance(response.get("files"), list):
        raise ValueError("PSI file listing has no files array")
    files = []
    seen = set()

    def visit(nodes):
        for node in nodes:
            key = node.get("key", "")
            children = node.get("files", [])
            if children:
                visit(children)
            elif key and not node.get("directory", key.endswith("/")) and not key.endswith("/"):
                identity = (key, str(node.get("id", "")), str(node.get("version", "")))
                if identity in seen:
                    continue
                seen.add(identity)
                files.append({
                    "key": key,
                    "id": node.get("id"),
                    "version": node.get("version"),
                    "bytes": byte_count(node.get("bytes_size")),
                    "category": node.get("sortingCategory"),
                    "subcategory": node.get("subcategory"),
                    "restricted": node.get("restricted"),
                    "visible": node.get("visible"),
                    "updated": node.get("updated"),
                })

    visit(response["files"])
    return sorted(files, key=lambda item: (item["key"], str(item["id"])))


def discover(root, timeout):
    """Page through the exact Combustion Science research-area filter."""
    provenance, records, seen = [], [], set()
    offset = 0
    while True:
        parameters = {
            "type": "investigation", "ffield": "Research Area",
            "fvalue": "combustion science", "from": offset, "size": 100,
        }
        response = fetch_json(
            API + "/repo/search?" + urlencode(parameters),
            root / "res" / "catalog" / f"search-{offset:05d}.json", provenance, timeout,
        )
        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total = total["value"] if isinstance(total, dict) else total
        for hit in hits:
            source = hit["_source"]
            accession = source["Accession"]
            if not re.fullmatch(r"PSI-\d+", accession):
                raise ValueError(f"Unexpected accession: {accession!r}")
            if source.get("Research Area", "").casefold() != "combustion science":
                raise ValueError(f"Unexpected research area for {accession}")
            if accession in seen:
                raise ValueError("Duplicate search result; retry to obtain a consistent catalog")
            seen.add(accession)
            records.append(source)
        offset += len(hits)
        if offset >= total:
            break
        if not hits:
            raise ValueError("PSI returned an incomplete search page")
    if not records:
        raise ValueError("PSI returned no combustion investigations")
    records.sort(key=lambda item: int(item["Accession"].split("-")[1]))
    write_json(root / "res" / "catalog" / "provenance.json", provenance)
    write_json(root / "res" / "catalog" / "datasets.json", [item["Accession"] for item in records])
    return [item["Accession"] for item in records]


def download_dataset(root, accession, timeout):
    directory = root / "res" / accession
    provenance = []
    metadata = fetch_json(API + "/repo/investigations/" + accession,
                          directory / "metadata.json", provenance, timeout)
    if metadata.get("accession") != accession:
        raise ValueError(f"Metadata accession mismatch for {accession}")
    payload = {
        "folder": accession + "/", "fileType": "study", "studyId": accession,
        "version": metadata["version"], "obfuscationcode": "",
    }
    listing = fetch_json(API + "/files/v2", directory / "files.json", provenance, timeout, payload)
    flatten_files(listing)  # Fail on an unexpected schema before reporting success.
    write_json(directory / "provenance.json", provenance)
    return accession


def inventory(root, accession):
    directory = root / "res" / accession
    metadata = json.loads((directory / "metadata.json").read_bytes())
    files = flatten_files(json.loads((directory / "files.json").read_bytes()))
    provenance = json.loads((directory / "provenance.json").read_bytes())
    sizes = [item["bytes"] for item in files if item["bytes"] is not None]
    reported = byte_count(metadata.get("totalFileSize"))
    known_total = sum(sizes)
    missing = len(files) - len(sizes)
    url = BASE + "/physci/repo/data/investigations/" + accession
    lines = [
        f"# {accession}: {cell(metadata.get('title'))}", "",
        "Inventory generated from NASA PSI metadata. Experimental files were not downloaded.", "",
        f"- Source: [{accession}]({url})",
        f"- Metadata retrieved: {provenance[0]['retrieved_at']}",
        f"- Version: {cell(metadata.get('version'))}",
        f"- Acronym: {cell(metadata.get('investigationAcronym'))}",
        f"- Research area: {cell(metadata.get('researchArea'))}",
        f"- Subarea: {cell(metadata.get('subResearchArea'))}",
        f"- Platform: {cell(metadata.get('flightProgram'))}",
        f"- Project type: {cell(metadata.get('projectType'))}",
        f"- DOI: {cell(metadata.get('doi'))}",
        f"- License: {cell(metadata.get('licenseIdentifier'))}",
        f"- Files listed: {len(files):,}",
        f"- Dataset size reported by PSI: {size_label(reported)} ({reported if reported is not None else 'unknown'} bytes)",
        f"- Sum of known file sizes: {size_label(known_total)} ({known_total:,} bytes)",
        f"- Files without a reported size: {missing:,}",
        f"- Raw responses: [metadata](../res/{accession}/metadata.json), [file listing](../res/{accession}/files.json), [provenance](../res/{accession}/provenance.json)",
    ]
    if not missing and reported is not None and reported != known_total:
        lines += ["", "PSI's dataset total differs from the sum of its file listing. Both values are retained."]
    objective = metadata.get("objective")
    if objective:
        lines += ["", "## Objectives from PSI", "", str(objective).strip()]
    lines += ["", "## File formats", "", "| Extension | Files | Known bytes |", "| --- | ---: | ---: |"]
    extensions = sorted({Path(item["key"]).suffix.lower() or "(none)" for item in files})
    for extension in extensions:
        group = [item for item in files if (Path(item["key"]).suffix.lower() or "(none)") == extension]
        lines.append(f"| {cell(extension)} | {len(group):,} | {sum(item['bytes'] or 0 for item in group):,} |")
    lines += ["", "## Remote files", "", "Sizes use decimal units (1 GB = 1,000,000,000 bytes). Keys and categories come from PSI.", "",
              "| File key | Category | Subcategory | Version | Size | Bytes | Restricted | Visible |",
              "| --- | --- | --- | --- | ---: | ---: | --- | --- |"]
    for item in files:
        values = [item["key"], item["category"], item["subcategory"], item["version"],
                  size_label(item["bytes"]), item["bytes"], item["restricted"], item["visible"]]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    write_bytes(root / "metadata-info" / f"{accession}.md", ("\n".join(lines) + "\n").encode())
    return {
        "accession": accession, "title": metadata.get("title"), "url": url,
        "version": metadata.get("version"), "file_count": len(files),
        "reported_bytes": reported, "listed_bytes": known_total, "unknown_sizes": missing,
        "retrieved_at": provenance[0]["retrieved_at"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Project root")
    parser.add_argument("--offline", action="store_true", help="Rebuild reports from saved metadata")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent metadata requests (default: 4)")
    parser.add_argument("--timeout", type=float, default=60, help="Network timeout in seconds (default: 60)")
    args = parser.parse_args()
    if args.workers < 1 or args.timeout <= 0:
        parser.error("workers and timeout must be positive")
    root = args.root.resolve()
    if args.offline:
        accessions = json.loads((root / "res" / "catalog" / "datasets.json").read_bytes())
    else:
        accessions = discover(root, args.timeout)
        errors = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(download_dataset, root, accession, args.timeout): accession for accession in accessions}
            for future in as_completed(pending):
                accession = pending[future]
                try:
                    future.result()
                    print(f"Saved metadata: {accession}", flush=True)
                except Exception as error:
                    errors.append(accession)
                    print(f"Failed {accession}: {error}", file=sys.stderr)
        if errors:
            raise RuntimeError(f"Metadata incomplete for {len(errors)} datasets; inventories were not regenerated")
    datasets = [inventory(root, accession) for accession in accessions]
    write_json(root / "res" / "catalog" / "inventory.json", datasets)
    print(f"Updated {len(datasets)} inventories in metadata-info/. No experimental files downloaded.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
