# Storage and import contract

This contract defines B2 (#17), B3 (#18), B5 (#20) and B6 (#21), implemented in `backend/catalog.py`. Active imports use `pipeline/schemas/` and current prepared data. The unchanged [pinned schemas](schemas/provenance.json) and [S0 fixtures](../../data/fixtures/s0/manifest.json) retain the historical handoff. See [build commands](../BACKEND.md).

## Entities

Use four SQLite tables. Keep each input record as JSON text as well as the columns needed for identity, references and queries. JSON preserves upstream field names, nulls, arrays and review objects. Do not flatten a card into a replacement response format.

| Table | Primary key | Required retained content |
| --- | --- | --- |
| `investigations` | `accession` | `metadata_version`, `snapshot_retrieved_at`, `metadata_sha256`, `source_url`, scientific metadata and the saved metadata reference. The current metadata version is an integer independent of file versions. |
| `cards` | `accession`, foreign key to investigations | `source_version`, complete research-card JSON, evidence references, generation and review. One current card per investigation. |
| `evidence` | Exact upstream `id` | `investigation` (foreign key), `passage_id`, `excerpt`, `source_url`, complete `locator` and evidence JSON. Never replace the ID with a database row number. |
| `remote_files` | `(accession, file_id, version)` | `key`, `filename`, nullable `category`, lowercase dotted `extension`, nullable `bytes`, `access`, nullable `download_sha256` and the complete catalog record. Investigation foreign key required. |

`inputs/investigations.json` is the local investigation adapter format. `inputs/remote-files.json` is the catalog adapter format. Their structures are defined in [storage-input.schema.json](storage-input.schema.json). Cards, packets and normalized tables use Alan's schemas directly. A remote-file record uses `common.remoteFile` identity with catalog fields; a sample-download manifest is not a complete catalog.

Copy the complete saved PSI file listing in a full catalog build. Access is `hidden` when `visible` is false, otherwise `restricted` when `restricted` is true, otherwise `public`. Derive the extension from the filename and lowercase it. Missing sizes remain null. Do not create download hashes from catalog metadata. The fixture has only two table entries and makes no complete-catalog claim.

## Validation before import

1. Verify source-byte hashes against saved provenance and available downloaded bytes. Validate schemas, exact passages, locators, source identity and date/URI formats offline. Store canonical prepared-record fingerprints. No production prepared-artifact hash manifest is supplied; do not claim an independent prepared-artifact hash check. The historical fixture manifest remains independently checked.
2. Require unique investigation accessions and card accessions. A card's `source_version` must equal its investigation's `metadata_version`. Reject conflicting duplicates within one batch.
3. Resolve every evidence reference in summaries, claims, comparisons, safety categories, findings, limitations and modeling resources. Each excerpt must occur exactly in its supplied passage. Its locator and investigation must match the packet. Recompute the whitespace-normalized excerpt suffix: collapse whitespace with `" ".join(excerpt.split())`, UTF-8 encode, take SHA-256 and retain the first 12 lowercase hexadecimal characters.
4. Require unique claim IDs within a card. Finding `observation` references a `reported_observation`; `implication` references a `potential_application`. Reject missing or mistyped claim references. Resolve modeling-resource file keys to the supplied catalog for that investigation.
5. Require each remote-file accession to exist and match the accession in its key. Distinct versions remain distinct records. Evidence ID collisions with different content are errors, including collisions across metadata versions; coordinate an upstream ID fix rather than overwriting cited evidence.
6. Reconcile source counts, imported rows and index counts. For normalized tables, compare original cells and data-row positions with the saved CSV, validate units and bounds, and retain invalid readings only as source text. Source-record counts are not verified experiment counts.

Review and structural validity answer different questions. Preserve `not_required`, `pending`, `approved` and `rejected` without promotion. The fixture profile permits pending material for integration development and must display that state. A reviewed release must satisfy the team's scientific-review requirements before publishing findings; passing this validator is not that approval.

## Idempotence and current records

An identical import is a no-op for entity content and row counts. Compute prepared-record fingerprints from a canonical JSON representation (sorted keys, compact separators, UTF-8, no non-finite numbers); store these separately from source hashes. Do not use a fingerprint as a public ID.

Upsert investigations and cards by accession when a newer source version arrives. A changed record at the same source version updates the current prepared record when it passes all checks; preparation and review can change without a PSI version change. Reject an older metadata/card version unless a separately requested rollback supplies a complete validated snapshot. Reconcile evidence references in the same transaction. A card change must not leave dangling references or delete evidence used by another active record.

Upsert remote files by the three-part key. A changed catalog entry updates its metadata. Preserve separate file versions. A different non-null downloaded hash for the same remote identity requires investigation; do not silently accept changed bytes. Subset imports never delete absent files or studies. Only an explicitly complete replacement snapshot can remove absent current records, after reference validation.

FTS content is derived from the accepted current records. Rebuild or update it in the same replacement build. Search titles, acronyms and cited scientific text while retaining claim types and evidence IDs. Numeric relevance weights and reviewed synonym lists belong to B3 implementation and evaluation, not to scientific assertions in these fixtures.

## Safe database replacement

Build a separate candidate database with foreign-key enforcement. Import in a transaction, build indexes, then check schema/reference validity, `PRAGMA foreign_key_check`, `PRAGMA integrity_check`, counts, representative detail lookups and FTS availability. Roll back and discard the candidate on any error.

Close candidate writers before switching the active database reference. The importer uses a validated candidate and atomic file replacement; readers open a read-only connection per operation. A failed build or Windows file switch leaves the last valid database active. Health reads the active generation. `python -m scripts.build_backend` supplies the offline build command.

## Hashes and provenance

| Hash | Meaning |
| --- | --- |
| Metadata provenance `sha256` | Exact saved PSI HTTP response bytes. |
| Run-table `source.sha256` / `download_sha256` | Exact downloaded CSV/file bytes. |
| PDF locator `sha256` | Exact PDF bytes, not extracted text. |
| Fixture manifest artifact `sha256` | Bytes of the prepared fixture file at the named relative path. |
| Canonical prepared-record fingerprint | Change detection for an imported JSON record. |
| Candidate database hash, if recorded | A prepared database artifact, never a source-file identity. |

Do not substitute one of these hashes for another. Source versions, retrieval dates and pending review travel with the data even when the prepared artifact changes.
