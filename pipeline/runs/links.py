"""Link run records to the experimental files of their investigation (PLAN A9).

A link is made only from an identifier the table records (a sample and test id, a FLEX
test number, a camera id) found in a file name of the saved PSI file list. Matching is
case-insensitive and token-bounded: the identifier must not touch another letter or digit,
so test ``T1`` never matches ``T12``. An underscore is a boundary, so ``21196M2_data`` is test
``21196M2``; but when another row of the table records a longer identifier that contains it
(``21196M2_1``), a file name that spells the longer one belongs to that row only. Nothing is inferred
beyond that.

Status. ``confirmed``: every identifier the rule looks for matched and, where the table has
the identifier in several rows, it still points at one row. ``ambiguous``: only one of two
required identifiers matched (BASS-II sample without test, or test without sample), or the
identifier is shared by several rows of the table. Ambiguous links are candidates for review.

Tables without a rule get no links. What was checked and rejected is stated next to each
rule below. Links are sorted by file name, file id and version so output is deterministic.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace

from pipeline.catalog import RemoteFile
from pipeline.runs.tables import collapse
from pipeline.runs.values import FileLink, LinkStatus, Record

Matcher = Callable[[Sequence[Record], Sequence[RemoteFile]], Iterator[tuple[str, FileLink]]]
"""Yields (record id, link) pairs for the records of one table."""


def _token(pattern: str) -> re.Pattern[str]:
    """The pattern, bounded so it neither follows nor precedes a letter or digit."""
    return re.compile(rf"(?<![A-Za-z0-9])(?:{pattern})(?![A-Za-z0-9])", re.IGNORECASE)


def _link(file: RemoteFile, basis: str, status: LinkStatus) -> FileLink:
    return FileLink(file.accession, file.file_id, file.key, file.version, file.filename, basis, status)


def _cell(record: Record, *names: str) -> str:
    wanted = {collapse(name) for name in names}
    return next((collapse(text) for column, text in record.original.items() if collapse(column) in wanted), "")


# --- identifier rules (FLEX, Saffire, CFI, Flame Design, CFI-G) ----------------------------------


@dataclass(frozen=True)
class Identifier:
    """One recorded identifier and the file-name pattern that spells it."""

    label: str
    columns: tuple[str, ...]
    pattern: Callable[[str], str | None]
    """The regex for a cell value, or None when the value is not an identifier (blank, n/a)."""


def _exact(value: str) -> str | None:
    return re.escape(value) if value and value.lower() != "n/a" else None


def _no_spaces(value: str) -> str | None:
    return _exact(value.replace(" ", ""))


def _flex_number(value: str) -> str | None:
    return rf"FLEX[-_]0*{int(value)}" if value.isdigit() else None


def _enclosed_values(spellings: dict[str, re.Pattern[str]], filename: str) -> set[str]:
    """Values whose spelling in the file name lies inside the spelling of another, longer value.

    ``21196M2`` is inside ``21196M2_1`` in ``..._21196M2_1_data.csv``: the file is test ``21196M2_1``'s.
    """
    spans = {value: [m.span() for m in pattern.finditer(filename)] for value, pattern in spellings.items()}
    return {
        value
        for value, inner in spans.items()
        if inner
        and any(
            all(
                any(start <= a and b <= end and (b - a) < (end - start) for start, end in outer)
                for a, b in inner
            )
            for other, outer in spans.items()
            if other != value
        )
    }


def _identifier_matcher(identifiers: Sequence[Identifier]) -> Matcher:
    def match(records: Sequence[Record], files: Sequence[RemoteFile]) -> Iterator[tuple[str, FileLink]]:
        tests = [record for record in records if record.kind != "note"]
        sharing = {
            identifier.label: Counter(_cell(record, *identifier.columns) for record in tests)
            for identifier in identifiers
        }
        spellings = {
            identifier.label: {
                value: _token(pattern)
                for value in sharing[identifier.label]
                if (pattern := identifier.pattern(value)) is not None
            }
            for identifier in identifiers
        }
        enclosed = {
            identifier.label: {
                file.file_id: _enclosed_values(spellings[identifier.label], file.filename) for file in files
            }
            for identifier in identifiers
        }
        for record in tests:
            found: dict[str, tuple[RemoteFile, list[str], list[LinkStatus]]] = {}
            for identifier in identifiers:
                value = _cell(record, *identifier.columns)
                pattern = identifier.pattern(value)
                if pattern is None:
                    continue
                status: LinkStatus = "confirmed" if sharing[identifier.label][value] == 1 else "ambiguous"
                bounded = _token(pattern)
                for file in files:
                    hit = bounded.search(file.filename)
                    if hit is None or value in enclosed[identifier.label][file.file_id]:
                        continue
                    basis = f'{identifier.label} {value} matches "{hit.group(0)}" in the file name'
                    if status == "ambiguous":
                        basis += f" (the same {identifier.label} is in several rows)"
                    entry = found.setdefault(file.file_id, (file, [], []))
                    entry[1].append(basis)
                    entry[2].append(status)
            for file, bases, statuses in found.values():
                overall: LinkStatus = "confirmed" if all(s == "confirmed" for s in statuses) else "ambiguous"
                yield record.id, _link(file, "; ".join(bases), overall)

    return match


_CAMERA_ID = r"S\d+C\d"


def _camera(value: str) -> str | None:
    return _exact(value) if re.fullmatch(_CAMERA_ID, value, re.IGNORECASE) else None


_SAFFIRE_CAMERAS = _identifier_matcher(
    (
        Identifier("Camera 1", ("Camera 1",), _camera),
        Identifier("Camera 2", ("Camera 2",), _camera),
    )
)
_FLEX_IDENTIFIERS = _identifier_matcher(
    (
        Identifier("FLEX Test #", ("FLEX Test #",), _flex_number),
        Identifier("FLEX Identifier", ("FLEX Identifier",), _exact),
    )
)
_CFI_IDENTIFIERS = _identifier_matcher(
    (
        Identifier("Flex Number", ("Flex Number",), _flex_number),
        Identifier("CIR", ("CIR",), _exact),
    )
)
_TEST_ID = _identifier_matcher((Identifier("Test", ("Test",), _exact),))
_TEST_ID_NO_SPACES = _identifier_matcher((Identifier("Test", ("Test",), _no_spaces),))


# --- BASS-II ------------------------------------------------------------------------------------

_SAMPLE_CELL = re.compile(r"^0*(\d+)[A-Za-z]?$")
_TEST_CELL = re.compile(r"^([A-Za-z]+)0*(\d+)([a-z]?)$")


def _bass_ii_sample_pattern(sample: str) -> str | None:
    """File spellings of a sample: ``SAMPLE_131``, ``sample139``, ``S131M``, ``S39M`` for ``39M``."""
    match = _SAMPLE_CELL.match(sample)
    return rf"(?:SAMPLE[ _-]?|S)0*{match.group(1)}[A-Z]?" if match else None


def _bass_ii_test_pattern(test: str) -> str | None:
    """File spellings of a test: ``TEST_T5``, ``TESTB16``, ``test T5``, ``TPT5`` and padded ``TPT09``."""
    match = _TEST_CELL.match(test)
    if match is None:
        return None
    prefix, number, suffix = match.groups()
    return rf"(?:TEST[ _-]?|TP){prefix}0*{number}{suffix}"


def _bass_ii(records: Sequence[Record], files: Sequence[RemoteFile]) -> Iterator[tuple[str, FileLink]]:
    for record in records:
        if record.kind == "note":
            continue
        sample, test = _cell(record, "Sample #"), _cell(record, "Test #")
        sample_pattern, test_pattern = _bass_ii_sample_pattern(sample), _bass_ii_test_pattern(test)
        if sample_pattern is None or test_pattern is None:
            continue
        sample_match, test_match = _token(sample_pattern), _token(test_pattern)
        for file in files:
            by_sample, by_test = sample_match.search(file.filename), test_match.search(file.filename)
            other_test = _token(r"(?:TEST[ _-]?|TP)[A-Za-z]+0*\d+[a-z]?").search(file.filename)
            other_sample = _token(r"(?:SAMPLE[ _-]?|S)0*\d+[A-Za-z]?").search(file.filename)
            if (by_sample and not by_test and other_test) or (by_test and not by_sample and other_sample):
                continue
            if by_sample and by_test:
                basis = (
                    f'sample {sample} ("{by_sample.group(0)}") and test {test} ("{by_test.group(0)}") in the file name'
                )
                yield record.id, _link(file, basis, "confirmed")
            elif by_sample:
                basis = f'only sample {sample} ("{by_sample.group(0)}") is in the file name; test {test} is not'
                yield record.id, _link(file, basis, "ambiguous")
            elif by_test:
                basis = f'only test {test} ("{by_test.group(0)}") is in the file name; sample {sample} is not'
                yield record.id, _link(file, basis, "ambiguous")


# Checked and not linked: BASS (PSI-26) raw files are named by date or ISS image id, not by run;
# Saffire-II/III also have "Sample n" files (a sample number is not a camera id, so not used);
# the ACME tables list a test day (YYDDD) that is only the prefix of test names ("17319C1"), not a token;
# SAME and SAME-R test numbers ("50") are bare numbers that also occur in unrelated names.
LINK_RULES: dict[str, Matcher] = {
    "bass-ii": _bass_ii,
    "flex": _FLEX_IDENTIFIERS,
    "saffire-1": _SAFFIRE_CAMERAS,
    "saffire-2": _SAFFIRE_CAMERAS,
    "saffire-3": _SAFFIRE_CAMERAS,
    "cfi": _CFI_IDENTIFIERS,
    "flame-design-inverse-flame": _TEST_ID,
    "flame-design-normal-flame": _TEST_ID,
    "cfi-g-inverse-flames": _TEST_ID_NO_SPACES,
    "cfi-g-normal-flames": _TEST_ID_NO_SPACES,
}


def add_links(slug: str, records: list[Record], files: Sequence[RemoteFile]) -> list[Record]:
    """The records with the file links of the table's rule; unchanged when the table has none."""
    matcher = LINK_RULES.get(slug)
    if matcher is None:
        return records
    found: dict[str, list[FileLink]] = {}
    for record_id, link in matcher(records, files):
        found.setdefault(record_id, []).append(link)
    return [replace(record, links=tuple(sorted(found.get(record.id, ()), key=_order))) for record in records]


def _order(link: FileLink) -> tuple[str, str, int]:
    return link.filename, link.file_id, link.version
