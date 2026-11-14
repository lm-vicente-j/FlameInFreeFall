"""Download the small per-run tables PSI publishes for each combustion investigation.

Fetches every file in an "Experimental table" category plus the BASS test-matrix
spreadsheets listed in metadata-info/. Together they are a few hundred kilobytes.
Run scripts/download_metadata.py first so the inventories are current.

    python scripts/fetch_experimental_tables.py [--out res/experimental-tables]
"""
import argparse
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://psi.nasa.gov/geode-py/ws/studies"
HEADERS = {"User-Agent": "FlameInFreeFall-Metadata/1.0"}
TRUSTED_HOSTS = ("https://psi-repo-prod.s3.amazonaws.com/", "https://psi-curation-prod.s3.amazonaws.com/")
ROW = re.compile(r"\| (psi-data/[^|]+?) \| ([^|]+) \| [^|]+ \| (\d+) \|")


def wanted(key, category):
    return category == "Experimental table" or re.search(r"Test[ .]Matri", key) is not None


def fetch(url, timeout=120):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=timeout) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=root / "res" / "experimental-tables")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    count = 0
    for inventory in sorted((root / "metadata-info").glob("PSI-*.md")):
        accession = inventory.stem
        for line in inventory.read_text(encoding="utf-8").splitlines():
            match = ROW.match(line)
            if not match or not wanted(match[1], match[2]):
                continue
            name = match[1].rsplit("/", 1)[1]
            # PSI resolves files by bare filename and file version, not by full key.
            query = urlencode({"file": name, "version": match[3], "redirect": "false"})
            signed = fetch(f"{API}/{accession}/download?{query}", timeout=60).decode().strip()
            if not signed.startswith(TRUSTED_HOSTS):
                print(f"skipped {accession} {name}: {signed[:80]}")
                continue
            data = fetch(signed)
            (args.out / name).write_bytes(data)
            count += 1
            print(f"{accession}\t{len(data):>7} B\t{name}")
    print(f"Saved {count} files to {args.out}")


if __name__ == "__main__":
    main()
