# HTTP contract

[openapi.json](openapi.json) defines all eight proposed GET endpoints. Embedded cards, evidence and run records reference Alan's unchanged schemas. The contract freezes supported behavior for backend development; it remains subject to shared S0 review.

| Endpoint | Result | Status |
| --- | --- | --- |
| `/api/studies` | Complete cards with matching evidence in metadata | Supported |
| `/api/studies/{accession}` | Complete card and comparison attributes | Supported |
| `/api/studies/{accession}/files` | Remote catalog entries | Supported |
| `/api/evidence/{id}` | Exact excerpt, locator and source URL | Supported |
| `/api/runs` | Unmodified normalized source records | Envelope supported; filters and experiment semantics provisional |
| `/api/runs/{id}` | One source record and its table provenance | Record preservation supported; graph interpretation provisional |
| `/api/coverage` | Explicit provisional state | Counts and regions blocked |
| `/api/health` | Active-data readiness, snapshot date and loaded counts | Supported; verified experiment count provisional |

## Shared rules

Success responses contain exactly `data` and `meta`. The data object or list retains upstream record fields. Pagination, relevance, source-table context and readiness metadata stay outside those records. Responses use `application/json`.

Study, file and run lists accept integer `limit` (default 20, range 1–100) and `offset` (default 0, minimum 0). `meta.total` counts all matching records before slicing; `limit` and `offset` report the effective values. A supported query with no matches, or an offset beyond the last match, returns 200 and `data: []`. A missing catalog or graph returns 503. It does not return an empty list implying a completed search.

Reject unknown or repeated query parameters, malformed decoded identifiers, non-integer pagination, unsupported enum values, non-finite numbers and reversed numeric bounds with 400. Decode identifiers once and validate before lookup. Validate parameters before checking availability, then check availability before resource existence. An unavailable dataset cannot establish that a resource is absent. Query values are ordinary text or typed numbers; never execute raw FTS or SPARQL syntax.

Errors contain exactly `{error: {code, message, details}}`. `details` always contains `state`, nullable `resource`, `parameters` (the invalid or contract-pending parameter names, otherwise empty) and nullable `health`. Do not expose exception traces.

| HTTP | `error.code` | Meaning |
| --- | --- | --- |
| 400 | `invalid_parameters` | Invalid path/query values. |
| 404 | `not_found` | A well-formed resource ID is absent from an available dataset. |
| 503 | `data_unavailable` | Required prepared data, a known evidence body or readiness information is unavailable. |
| 500 | `internal_error` | Unexpected failure after request validation. |

The examples in [expected/http.json](../../data/fixtures/s0/expected/http.json) describe independent load states. A resource can exist in one case and be unavailable in another. They are contract examples, not recorded server responses.

## Studies and evidence

`q` defaults to an empty string and accepts up to 200 characters. Trim surrounding whitespace. Split nonempty input on whitespace into literal, case-insensitive search terms; require every term to occur in the indexed cited content, title or acronym. Punctuation has no query-language meaning. B3 assigns relevance weights; sort by score descending and accession ascending for ties. With no query, order by numeric accession ascending. Do not report relevance as risk.

`safety_category` accepts one of `prevention`, `detection` or `suppression`. Combine it with `q` using AND. Match only cited card categories. These metadata-only fixtures have no reviewed safety categorization, so `safety_category=prevention` returns an empty list. Do not infer categories from the title.

`meta.matches` is empty for an unsearched list. For a search it contains one item per returned card: `accession`, global 1-based `rank`, nullable `score` and exact matching `evidence` records. A null fixture score means ranking has not been implemented. Do not fabricate an excerpt when a title/acronym match has no evidence passage; return an empty evidence list for that match.

Examples: `/api/studies?q=droplet&limit=20&offset=0` and `/api/studies?q=smoke&safety_category=detection`. Detail lookup returns the card unchanged. `meta.evidence_state` is `available` when all its evidence bodies can be resolved and `unavailable` otherwise; it does not imply scientific approval.

Evidence IDs include `#`. Percent-encode the whole path ID, especially `%23` for `#`; an unencoded fragment never reaches the server. For example, replace `{id}` with the encoded ID from the fixture's path parameters. A known unavailable excerpt returns 503 with `details.state=evidence_unavailable`; an unknown ID in an available evidence store returns 404. A metadata locator remains a metadata locator; do not invent PDF pages.

## Remote files

`filename` defaults to empty and matches a case-insensitive literal substring. `category` matches the complete category case-insensitively. `extension` requires a leading dot and matches case-insensitively. Combine filters with AND. Return normalized lowercase extensions; preserve the source category and filename. Sort by casefolded filename, exact filename, file ID and ascending version. These rules also define pagination stability.

Example: `/api/studies/PSI-69/files?filename=flex&category=Experimental%20table&extension=.csv&limit=20&offset=0`.

The parent investigation must exist. An unknown parent returns 404; a known parent with no matching files returns 200 and an empty list. A catalog entry describes a remote file and its access state. It does not establish that its contents were processed. `download_sha256` is null unless actual downloaded bytes were verified. The production source is the full saved catalog, not the curated download manifest.

## Runs and coverage

Run list/detail `data` retains the exact `run-table.record` structure. `meta.source` for detail and `meta.sources` for lists carry investigation, table and source information absent from the record schema. This links a row to its source CSV without inventing per-run experimental-file or report-evidence links.

Unfiltered pagination counts source records, including notes, and uses accession number, table slug and numeric row order. `meta.count_basis=source_records` and `provisional=true` prevent interpreting `total` as individual experiments. Fixtures contain selected rows only; their total is six, not the total of the source tables.

The proposed typed filters are `fuel_class`, `material`, `geometry`, `flow_direction`, `o2_min`, `o2_max` (percent), `pressure_min`, `pressure_max` (kPa), `flow_min`, `flow_max` (cm/s) and `outcome`. Parameter names/types are available for review; matching ranges/sweeps, comparing hardware and associating gravity remain unresolved in #33–#35. There is no frozen gravity parameter. Do not implement these unresolved filters by assuming overlap, containment, missing-value substitution or cross-hardware equivalence. Requests using a provisional filter return 503 with `details.state=contract_pending` until its semantics are agreed; malformed values still return 400.

Coverage returns 200 with `data.state=provisional`, `verified_run_count=null`, `regions=null` and the blocker IDs when the graph is available. Null regions are not empty regions and must not display as “not in PSI.” Region bounds, bins, denominator, duplicate handling, comparison groups and empty-region labels remain unfrozen. A missing graph returns 503. Filtering a provisional coverage request follows the same `contract_pending` rule.

## Health

Readiness describes the active validated data. `ready` means both catalog and graph are loaded; `degraded` means exactly one is available; `unavailable` means neither is available. Ready/degraded responses use 200. With neither dataset available, return 503 and include the `Health` object in `error.details.health`.

`snapshot_date` is the UTC date of the oldest source retrieval in the active snapshot, or null when no active snapshot exists. The fixture snapshot date is 2026-11-14. `investigation_count` counts actual loaded investigations. `run_record_count` counts actual loaded run-table records, including notes. An available, empty dataset has count zero; an unavailable dataset has count null. `verified_run_count` remains null until classification/count rules are agreed. Readiness does not certify scientific approval or coverage completeness.

## Validation

Run `python docs/contracts/validate.py` from the repository root with Python 3.10+ and the existing `jsonschema` and `referencing` packages. The validator works offline; no packages were installed for this change.

Validation passes for eight unchanged pinned schemas, the OpenAPI 3.1 document, two investigation/catalog records, two cards, two evidence packets, six selected source rows, 37 HTTP cases and 426 RDF triples. It also rejects six altered fixtures. Checks cover source/artifact hashes, evidence references, original cells, units and supported RDF assertions. The Turtle check covers the fixture's N-Triples subset; it is not a general RDF parser or an integration test of a backend.

Scientific review remains pending. Range/session/duplicate classification, dedicated initial/final fields and per-run file/evidence links require upstream schema agreement. Flow sweeps, comparisons and gravity filters remain unresolved in #33–#35. Alan must review the representative data and Emmanuel must review requests and display requirements before S0 #6 can close.
