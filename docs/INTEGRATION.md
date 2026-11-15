# Pipeline integration record

This record tracks the corrections for #42 before merging #40 and #41 into `main`. Scientific review remains separate from structural validation. Pending aliases, extractions and cards are not approved by this integration.

## Download, validation and normalization

- API response bodies are capped at 16 KiB. Their bytes, retry bytes and file bytes share one cumulative budget, capped at 250 MB. The same manifest carries the ledger between runs. An invalid manifest cannot reset the ledger; a legacy manifest with incomplete history permits cache reads only.
- Redirects stay within the PSI allowlist. Malformed signed URLs become explicit file failures. HTTP 4xx responses are not retried. Transient file failures have bounded retries, and one deadline covers each file's API and transfer attempts.
- New manifests retain source URLs, investigation URLs, snapshot versions, retrieval dates and metadata/file-list hashes. Legacy download outcomes are retained as historical records.
- Date-time and URI validation uses explicit standard-library checks. Quantity bounds must be finite and satisfy `min <= max`. Lone surrogate characters are escaped in stored JSON so exact extracted text survives. The PDF command returns a failure status when an extraction fails or times out.
- FLEX composition checks allow the rounding error of four two-decimal fractions and include any recorded additional composition columns, such as argon. No missing gas concentration is invented.
- FLEX burning rate stays unknown because the source header does not establish a rate unit. BASS velocity stays unknown because the 2014 calibration is not verified for its 2012–2013 readings.
- BASS preserves the joined matrix values, physical cell addresses, sheet-row reference and workbook hash alongside the original CSV cells. Extraction proposals carry an exact column identifier. Air-display conversion cannot use a fan-display column.
- Negative ignition, extinction and blowoff labels remain verbatim `observation` outcomes. A file explicitly naming a different sample or test is excluded rather than retained as an ambiguous candidate.

## Reproducible checks

Install the existing runtime requirements and run the committed regressions:

```text
python -m pip install -r pipeline/requirements.txt
python -m unittest discover -s tests/pipeline -v
python -m pipeline.runs build
python docs/contracts/validate.py
```

Development checks use Ruff, Mypy and their JSON Schema/OpenPyXL type stubs in an isolated environment; they add no runtime dependencies:

```text
uv run --no-project --with ruff --with mypy --with types-jsonschema --with types-openpyxl --with-requirements pipeline/requirements.txt ruff check pipeline
uv run --no-project --with ruff --with mypy --with types-jsonschema --with types-openpyxl --with-requirements pipeline/requirements.txt mypy --strict pipeline
```

The `test_*` ignore rule is unchanged. Regression tests are added explicitly so another clone can run them. `pyproject.toml` records the lint/type settings. The Mypy check covers pipeline modules and does not follow the unchanged legacy metadata collector.

The source tables and PDFs remain downloaded inputs under ignored `res/`. Preparation commands require those saved inputs. Structural validation of committed contracts and fixtures runs offline without them.

PR #40 verification: 17 regression tests pass; Ruff passes; Mypy reports no errors in 31 pipeline modules. The regenerated output preserves 2,009 records across 22 tables. BASS-II has 567 confirmed links and 11 ambiguous candidates after excluding files that explicitly identify another test. No alias or extraction review status was promoted.

## Research cards and review

Card validation checks numbers written as words, comparator direction and quantity attribution within source clauses. Title metadata cannot turn objectives into reported observations; summaries, comparisons and finding conditions follow the same result-evidence rule. Source limitations need citations, and modeling file keys must belong to the investigation inventory.

The review screen includes comparison fields, safety categories, modeling resources, source locators and passage context. Malformed review files return an error without a traceback. The 24 pending cards describe available table evidence accurately. Their preparation drafts are committed under data/drafts/; the recorded generation timestamp allows deterministic finalization without inventing a new review.

Regenerate a card with `python -X utf8 -m pipeline.cards finalize data/drafts/PSI-69.json`. Validate all cards with `python -X utf8 -m pipeline.cards validate`. Regenerate the development subset with `python -m pipeline.fixtures`. Historical S0 fixtures retain their original schema pin and are separate from current pipeline fixtures.

PR #41 verification: the 17 download/normalization regressions and nine card/review regressions pass. All 24 saved drafts reproduce their committed cards, including timestamps and pending review. Ruff passes; Mypy reports no errors in 40 pipeline modules. The development fixtures regenerate successfully. These checks do not approve any scientific claim.

## Backend delivery

PR #44 adds Flask startup and eight GET endpoints, atomic SQLite imports, FTS5/BM25 search, RDF loading and bound SPARQL filters. D2/D3 decisions and search synonyms were approved by the user. Current HTTP responses use `docs/contracts/openapi-current.json`; the historical S0 bundle remains unchanged.

The combined backend suite passes 45 tests using tracked catalog/run fixtures, including real service-to-HTTP contract checks. Ruff and Mypy pass for application, backend and build/benchmark modules. Two full catalog builds reconcile 24 investigations/cards, 261 evidence items and 60,866 files. The graph preserves all 2,009 source records. The historical validator still passes its schemas, 37 HTTP cases, 426 RDF triples and six altered-fixture rejection cases.

The fixed ranking evaluation passes 11/12 top-three expectations and 3/3 unsupported-query checks. The 30-query HTTP benchmark passes with p95 775.26 ms and maximum 859.21 ms; all eight smoke routes succeed. Startup takes 52.65 s and is excluded from request latency. Committed reports are under `data/benchmarks/`; [BACKEND.md](BACKEND.md) gives reproducible commands. [CHANGED_FILES.md](CHANGED_FILES.md) lists the implementation's created and modified files.

Remaining limits: #6 needs frontend agreement; #23 stays open at the user's request because the frontend index and complete workflow are absent. Scientific cards, material aliases and extractions remain pending, so verified run count is zero. Prepared-record fingerprints and source-byte hashes are checked, but there is no independent production prepared-artifact hash manifest. No additional predictive behavior, dependencies beyond Flask/rdflib and the existing pipeline, or scientific approvals are inferred.

## Frontend delivery

Emmanuel's `feature-frontend-ui` HTML, CSS and JavaScript are now integrated with the existing Flask API. Search uses the server index and pagination; study details and evidence use actual card records and encoded evidence IDs. The file browser selects any investigation and combines filename, category and extension filters with pagination. API errors remain visible instead of triggering a mock fallback. Chart.js is stored locally with its license for offline use.

The runs table retains intervals, unknown quantities, extraction methods, source-row kinds, review states and gravity on each outcome. The chart plots known points on the visible page and the three atmosphere references. It does not infer zero conditions, run-level gravity or a coverage gap from missing data. Comparison, export and advanced condition/coverage views remain separate unfinished issues.

Verification passes 12 Node frontend regressions, all 45 backend tests and the real-data headless browser workflow. The browser check reaches all 24 investigations, opens details and exact citations, exercises file pagination and all three filters, handles empty results and simulated 503 recovery, and checks the mobile viewport. It reports no JavaScript exceptions or external page requests. Commands and limits are in [FRONTEND.md](FRONTEND.md).

PR #45's approvals are preserved. Rebuilding the current snapshot loads 24 cards, 261 evidence records, 60,866 files and 2,009 source rows; 506 rows meet the backend's verified-run criteria. This supersedes the earlier zero count and frontend-unavailable statements above. Three backend tests were adjusted only in temporary fixtures and expectations to account for those existing approvals; no scientific record or review was changed by frontend integration.

The [current benchmark](../data/benchmarks/frontend-integration-2026-11-15.json) passes all eight smoke routes and 30 timed queries, with p95 387.16 ms and maximum 387.71 ms. Startup takes 33.62 s outside the measured requests. This completes the frontend-assets blocker in B8 (#23); the broader frontend features and shared sign-off listed in [FRONTEND.md](FRONTEND.md) remain separate.
