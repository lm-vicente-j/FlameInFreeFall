"""Which table is which: file name -> accession, slug and normalizer.

Tables without an entry in ``NORMALIZERS`` use the generic normalizer, so every
row is still carried through. Register a deeper normalizer here (for example for
BASS and BASS-II) without touching anything else.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pipeline.runs.common import Normalizer
from pipeline.runs.normalizers import bass, flex, generic, saffire

_FILENAME = re.compile(r"^(?P<accession>PSI-\d+)_Experimental table_(?P<name>.+)\.csv$")

NORMALIZERS: dict[str, Normalizer] = {
    "bass": bass.BASS_NORMALIZER,
    "bass-ii": bass.BASS_II_NORMALIZER,
    "flex": flex.NORMALIZER,
    "saffire-1": saffire.NORMALIZER,
    "saffire-2": saffire.NORMALIZER,
    "saffire-3": saffire.NORMALIZER,
}


class RegistryError(ValueError):
    """A file name does not follow the table naming convention, or slugs collide."""


@dataclass(frozen=True)
class TableSource:
    accession: str
    slug: str
    path: Path

    @property
    def normalizer(self) -> Normalizer:
        return NORMALIZERS.get(self.slug, generic.NORMALIZER)


def slugify(name: str) -> str:
    """Lowercase, with each run of non-alphanumerics replaced by one hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_filename(path: Path) -> TableSource:
    match = _FILENAME.match(path.name)
    if match is None:
        raise RegistryError(f'{path.name}: expected "PSI-<n>_Experimental table_<name>.csv"')
    slug = slugify(match.group("name"))
    if not slug:
        raise RegistryError(f"{path.name}: table name has no letters or digits")
    return TableSource(match.group("accession"), slug, path)


def discover(directory: Path) -> list[TableSource]:
    sources = [parse_filename(path) for path in sorted(directory.glob("*.csv"))]
    seen: dict[str, str] = {}
    for source in sources:
        if source.slug in seen:
            raise RegistryError(f"{source.path.name}: slug {source.slug!r} already used by {seen[source.slug]}")
        seen[source.slug] = source.path.name
    return sorted(sources, key=lambda source: (int(source.accession[4:]), source.slug))
