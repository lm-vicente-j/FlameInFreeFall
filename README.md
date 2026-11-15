# Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data

A proposed dashboard for exploring NASA's Physical Sciences Informatics (PSI) combustion research and its relevance to spacecraft fire safety. Research cards summarize and compare investigations. A condition explorer shows which experimental runs cover a scenario, their recorded outcomes, and gaps in the saved PSI tables.

See [APPROACH.md](docs/APPROACH.md) for the proposal and data findings, and [PLAN.md](PLAN.md) for implementation details. The [accepted decisions](PLAN.md#accepted-decisions) define normalization priorities, gravity display, report scope, and limits on external coverage. Flow sweeps and cross-hardware comparisons remain under review. The repository provides metadata collection, inventories, and an experimental-table downloader.

## Objectives

- Make combustion research easier to find, compare, and understand.
- Identify research relevant to crewed spacecraft, stations, lunar and Martian bases, and pressurized rovers.
- Extract data to support predictive models of flammability and fire scenarios.
- Explore runs by oxygen, pressure, airflow, and material, with source links and explicit coverage gaps.
- Highlight research that informs fire prevention, detection, and suppression systems.
- Explore fire safety applications on Earth as an optional extension.

## Challenge Coverage

The table below describes planned work.

| Challenge objective | Plan coverage | What needs attention |
| --- | --- | --- |
| Interactive dashboard | Planned: search, filters, comparisons, evidence views, and a condition explorer | Complete and test the integrated workflow. |
| Summarize investigations | Planned: 24 skill-generated, reviewed research cards | Cite summaries and distinguish objectives, hypotheses, and findings. |
| Rank relevant investigations | Planned: local keyword search and relevance ranking | Explain matching evidence; do not present relevance as fire risk. |
| Interpret findings for fire safety | Planned: findings linked to experimental conditions and safety implications | Verify at least one finding for each core investigation. |
| Support predictive modeling | Planned: normalize experimental tables, map condition coverage, and link runs to measurements and remote files | Preserve source conditions and missing outcomes without claiming a validated predictive model. |
| Highlight improved safety controls | Planned: connect findings to prevention, detection, or suppression | Support each connection with evidence and distinguish proposed applications. |

## Considerations

Optional considerations:

- Design for students, professors, aerospace researchers, and engineers.
- Show experimental objectives, fuels, sample or burner geometry, oxygen concentration, airflow, sensors, and measurements.
- Compare conditions and results within and across investigations, accounting for differences in hardware.
- Consider oxygen enrichment and reduced pressure in proposed lunar habitats.

Scope and data limits:

- The challenge states that PSI has no partial gravity combustion data. Distinguish measurements from extrapolations to lunar or Martian gravity.
- Rocket and propellant fire safety generally falls outside the available PSI research.
- A fire simulator is not required by the challenge. Supporting predictive modeling does not require implementing a simulator.

Challenge sources: [Details](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/?tab=details) and [Resources](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/?tab=resources).

## 48-Hour MVP

Build a local research explorer with keyword search, investigation comparisons, cited insights, and a condition explorer. Use Python, Flask, SQLite FTS5/BM25, rdflib, pypdf, HTML, CSS, and vanilla JavaScript. Store cards, evidence, and the file catalog in SQLite. Store run conditions and outcomes in an in-memory RDF graph, queried with SPARQL through rdflib.

A skill generates research-card JSON from evidence packets during preparation. Validate records before import. Development records may retain clearly labeled pending cards, text mappings, and extracted observations; review them before using them as scientific results or verified coverage. Convert experimental tables to shared column names and units while preserving each record's source file, row, and original text. The application displays prepared content without generating answers at runtime.

```text
Investigation layer                         Run layer
PSI metadata + selected documents           Experimental tables + BASS test matrices
    -> extracted evidence                      -> parsing and reviewed normalization
    -> reviewed research-card JSON             -> records with source provenance
    -> SQLite catalog and keyword index        -> in-memory RDF graph / SPARQL
                   \                             /
                    -> dashboard: cards, comparisons, evidence, conditions, coverage gaps
```

| Component | Content | Purpose |
| --- | --- | --- |
| Research cards | Cited summaries, findings, safety implications, comparison attributes, and limitations | Explain each investigation using reviewed evidence. |
| Scientific index | Objectives, approach, hypotheses, research impacts, and selected document passages | Rank investigations and show matching evidence. |
| Run graph | Conditions, recorded outcomes, source links, and extraction/review status | Filter comparable records and map coverage without a run-distance score. |
| File catalog | Investigation, filename, category, format, version, size, and source reference | Browse remote files without downloading the full collection. |

Start with the saved metadata for all 24 investigations. All have objective, approach, hypothesis, and research-impact fields. These fields, titles, and acronyms total about 81,000 characters in the saved snapshot.

Use the existing sample of 12 PDFs across BASS-II, Saffire-I, SAME-R, and FLEX, three per investigation; 11 have a text layer. Keep the 250 MB total budget, 20-PDF maximum, and hour-12 collection cutoff. The sampled BASS-II ProofSheet contains camera metadata and no outcomes, so do not collect the remaining 124. Preserve download failures and missing text layers, use citable experimental-table rows where supported, and state missing evidence as a limitation. The metadata collector does not download these documents.

For each core investigation, verify at least one documented finding, its conditions, and a supported fire safety implication. Keep hypotheses and expected impacts labeled as such. A file appearing in the catalog does not mean its contents have been analyzed.

### Explore by experimental condition

The 2026-11-14 review in [APPROACH.md](docs/APPROACH.md) covers 22 experimental-table CSVs totaling about 230 KB and 2,010 non-empty rows, plus BASS test-matrix spreadsheets. The rows include individual runs, ranges, session summaries, and notes. Preserve these distinctions when counting tests. Four modeling-only investigations publish no experimental table.

The planned workflow is to:

1. Normalize recorded conditions and outcomes while preserving unknowns, original values, units, and provenance.
2. Filter by fuel class, material, geometry, and flow direction before comparing oxygen, pressure, and airflow.
3. Plot oxygen against pressure alongside a sortable runs table. Mark the three crew-atmosphere references: 14.7 psia at 21% O2, 10.2 psia at 26.5%, and 8.2 psia at 34%.
4. Show coverage gaps for the active filters. Label them "not in PSI"; they do not establish whether a scenario has been studied elsewhere or whether it is safe.
5. Link runs to source files and cited report passages. Show the authors' conclusions without adding our own.

The initial review found no solid-fuel run above 22.2% O2 or below about 0.97 atm in these tables. FLEX includes reduced-pressure, oxygen-enriched droplet tests; these do not establish coverage for solids.

BASS and BASS-II record flow as instrument readings. Converting them to velocity requires calibration for the test date and number of flow restrictors. Many BASS-II runs vary flow during the test. Reports may supply outcomes missing from the tables; unsupported outcomes remain unknown.

The accepted normalization order is FLEX and Saffire-II, followed by BASS and BASS-II. These four investigations are the minimum preparation target; preserve the other tables row by row and leave unsupported conditions unknown. If review time runs out, retain BASS/BASS-II proposals as pending rather than confirmed observations.

The MVP has no gravity filter. Preserve gravity per outcome and show Saffire-II's normal-gravity results with a visible "1 g ground test" label. Saffire-IV–VI and SoFIE coverage outside the saved PSI snapshot remains explicitly unverified and is outside the MVP verification scope. Flow-sweep behavior, calibration applicability, and cross-hardware comparison rules still require agreement. See the [accepted decisions and remaining questions](PLAN.md#accepted-decisions).


## Implementation Team

| GitHub user | Code ownership |
| --- | --- |
| `alan-pv` | Sample downloader, PDF extraction, evidence packets, research-card skill, card validation, and run normalization |
| `lm-vicente-j` | SQLite import, keyword ranking, RDF run graph, SPARQL queries, backend endpoints, and integration commands |
| `EmmanuelRamiro23` | Search interface, comparisons, evidence viewer, file browser, condition explorer, runs table, and JSON export |

## Schema contracts for backend work

For `lm-vicente-j`'s backend issues **B1-B8 (#16-#23)**, use Alan's JSON Schema 2020-12 contracts from [PR #38](https://github.com/lm-vicente-j/FlameInFreeFall/pull/38) as the data-contract baseline. This section documents commit [`680a9f1`](https://github.com/lm-vicente-j/FlameInFreeFall/commit/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf). The PR has merged; adopting its schemas for backend work does not complete the shared S0 agreement.

The linked schema files define the exact required fields, types, enums, references and property restrictions. Preserve their field names and nested structures when importing or exposing prepared data. Coordinate any required schema change with Alan and update the affected contracts before implementing it.

### Contract files

The links point to the pinned PR commit. Exact copies are available in [docs/contracts/schemas/](docs/contracts/schemas/), with [source commit and checksums](docs/contracts/schemas/provenance.json) for offline validation.

| Schema | Purpose | Required top-level fields |
| --- | --- | --- |
| [`common.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/common.schema.json) | Shared file identity, accessions, hashes, timestamps and review definitions. | Reusable definitions under `$defs`; no standalone record. |
| [`sample-selection.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/sample-selection.schema.json) | Curated download inputs. | `budget_bytes`, `files` |
| [`sample-manifest.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/sample-manifest.schema.json) | Downloaded/cached/failed file records and transfer accounting. | `generated_at`, `budget_bytes`, `transferred_bytes`, `files` |
| [`extracted-document.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/extracted-document.schema.json) | Page-preserving PDF extraction results. | `sha256`, `extractor`, `status`, `error`, `page_count`, `pages`; inherited file identity: `accession`, `file_id`, `key`, `version`. |
| [`evidence-packet.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/evidence-packet.schema.json) | Citable metadata fields and PDF passages for one investigation. | `investigation`, `title`, `acronym`, `metadata_version`, `source_url`, `snapshot_retrieved_at`, `coverage`, `passages`, `documents` |
| [`research-card.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/research-card.schema.json) | Cited summaries, typed claims, comparisons, findings and review. | `accession`, `source_version`, `title`, `acronym`, `coverage`, `summary`, `safety_categories`, `comparison`, `claims`, `findings`, `limitations`, `modeling_resources`, `evidence`, `generation`, `review` |
| [`run-table.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/run-table.schema.json) | Normalized source rows, conditions, outcomes and per-value provenance. | `table`, `investigation`, `source`, `counts`, `records` |
| [`alias-dictionary.schema.json`](https://github.com/lm-vicente-j/FlameInFreeFall/blob/680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf/pipeline/schemas/alias-dictionary.schema.json) | Reviewed mappings from source text to canonical values. | `name`, `entries` |

### Identity, provenance and review

- Investigation accessions match `PSI-<number>`. A remote-file reference carries `accession`, `file_id`, `key` and integer `version`. Keep file versions distinct from investigation metadata versions.
- Hashes are SHA-256 strings of 64 lowercase hexadecimal characters. Timestamps use the schema's `date-time` format.
- Review status is `not_required`, `pending`, `approved` or `rejected`. A review object contains `status`, `reviewer`, `reviewed_at` and `notes`; the reviewer and date may be null. Preserve these states rather than inferring approval from structural validity.
- A selection entry adds `purpose` (`evidence` or `run-normalization`) and `reason` to file identity. Manifest entries add filename, category, extension, bytes, access, purpose, status, hash, local path, retrieval time and error. Access is `public`, `restricted` or `hidden`; transfer status is `downloaded`, `cached` or `failed`.
- Extraction results use `extracted`, `no_text`, `failed` or `timeout`. Each page has a 1-based physical `number` and exact `text`. Keep extraction status separate from scientific review status.

### Cards and evidence

A research card's `summary` is cited text: `text` plus non-empty `evidence_ids`. Each `safety_categories` entry cites evidence for `prevention`, `detection` or `suppression`. `coverage` is `metadata_only` or `metadata_and_documents`.

The `comparison` object requires `fuels`, `geometry`, `oxygen`, `pressure`, `flow`, `gravity`, `measurements` and `hardware`. Each attribute is cited text or null when undocumented.

Claims contain `id`, `type`, `text` and `evidence_ids`. Claim IDs match `C<number>`; types are `objective`, `hypothesis`, `reported_observation` and `potential_application`. A finding links a reported-observation claim through `observation`, cited `conditions`, a potential-application claim through `implication`, and a safety `category`. Preserve the distinction between intended work and reported results.

An evidence packet preserves its investigation metadata version, snapshot time, passages and selected-document statuses, including failures. Passage IDs derive from their locators:

- Metadata: `PSI-<number>:meta:<field>`.
- PDF: `PSI-<number>:pdf:<file_id>:v<version>:p<page>`.
- Card evidence: `<passage_id>#<first 12 hex characters of the whitespace-normalized excerpt's SHA-256>`.

A card evidence record contains `id`, `passage_id`, `investigation`, `source_url`, `locator` and exact `excerpt`. Metadata locators contain `kind: metadata` and `field`. PDF locators contain `kind: pdf`, file identity, `filename`, `sha256` and a 1-based `page`.

### Normalized run records

A run-table document carries `table`, `investigation`, `source`, `counts` and `records`. The source preserves `filename`, `sha256`, `encoding` and exact header `columns`. Supported encodings are `utf-8`, `utf-8-sig` and `cp1252`.

Each record requires `id`, `kind`, `row`, `original`, `conditions`, `outcomes` and `review_status`. IDs use `<accession>:<table-slug>:<row>`; `row` is the 1-based data-row index after the header. `original` preserves every cell as a string keyed by its exact source header.

| Condition | Value and unit contract |
| --- | --- |
| `fuel_class` | Category: `solid`, `droplet`, `gas` or null. |
| `material`, `geometry`, `diluent` | Category: string or null. |
| `flow_direction` | Category: `concurrent`, `opposed`, `quiescent` or null. |
| `o2_percent` | Quantity with unit `percent`. |
| `pressure_kpa` | Quantity with unit `kPa`. |
| `flow_cm_s` | Quantity with unit `cm/s`. |

Every category or quantity carries `method`, `columns`, `review_status`, `quote` and `note`. Methods are `parsed`, `mapped`, `llm`, `manual` and `unknown`. A category adds `value`. A quantity adds nullable `min` and `max`, `unit` and `qualifier` (null or `approximate`). Equal bounds represent a point; differing bounds represent a range or sweep. Preserve unknowns as null and the original source text.

An outcome contains `type`, `gravity` and `result`. Its result is a category or quantity. Gravity is `microgravity` or `normal`, where `normal` denotes the reported 1 g comparison. Outcome types are `burn_time`, `burning_rate`, `extinction_diameter`, `test_end`, `burn_length`, `spread_length`, `spread_rate`, `ignition`, `extinction`, `blowoff`, `weight_loss_rate`, `flames_ignited` and `observation`.

Alias dictionaries contain `name` and `entries`. Each entry preserves `source`, `canonical`, `proposed_by` (`llm` or `manual`) and its `review`. Only human-approved mappings qualify as reviewed aliases.

### Application to backend issues

| Issue | Use of the contracts |
| --- | --- |
| **B1 #16**: Flask startup and health | Use snapshot metadata and validated import/load results for readiness and counts. The [HTTP contract](docs/contracts/API.md#health) defines the response. |
| **B2 #17**: SQLite importer | Import research cards and their evidence using the exact IDs, metadata versions, source references and review states. Retain file identity and hashes when importing file records. |
| **B3 #18**: Search | Index cited card content while preserving claim types, safety categories and evidence IDs for matching evidence. |
| **B4 #19**: RDF loader | Consume run-table conditions, outcomes, units, source-row identity and per-value provenance using the [supported RDF mapping](docs/contracts/RDF.md). Classification and coverage remain provisional. |
| **B5 #20**: Study and evidence endpoints | Preserve card fields and evidence records, including nullable comparison attributes, exact excerpts and locators. |
| **B6 #21**: File browsing | Preserve file identity, version, category, extension, bytes and access state. Use the complete saved PSI catalog; the sample manifest covers only selected downloads. |
| **B7 #22**: Runs and coverage | Preserve quantity bounds, units, gravity on outcomes, original cells and review states. Coverage counting must also satisfy the unresolved row-classification requirements below. |
| **B8 #23**: Builds and integration | Validate prepared inputs against the same schemas and check references, hashes, review requirements and source/count reconciliation during integration. |

After the pipeline is available, structural validation uses `pipeline.schema.schema_errors(instance, name)`, where `name` is the schema filename without `.schema.json`. An empty error list confirms structural validity. Evidence resolution, scientific support, approved mappings, valid measurements and count reconciliation still require semantic checks.

### Remaining contract decisions

The current run schema allows only `kind: run` or `kind: note`, with `counts.runs`, `counts.notes` and `counts.empty_rows_skipped`. It does not explicitly distinguish the ranges, session summaries and duplicates required by [PLAN.md](PLAN.md#shared-contracts), or provide dedicated fields for initial/final conditions, run-to-file links and supporting evidence IDs. Retain source data and coordinate these additions before implementing affected graph or coverage behavior.

These schemas define pipeline data. The [HTTP contract](docs/contracts/API.md), [storage contract](docs/contracts/STORAGE.md) and [RDF mapping](docs/contracts/RDF.md) define the backend interfaces, with shared FLEX/Saffire-II development fixtures. Alan and Emmanuel still need to review the contracts and fixtures before closing [S0 #6](https://github.com/lm-vicente-j/FlameInFreeFall/issues/6). Flow sweeps and comparison rules remain open in #33 and #34. The accepted #35 decision preserves outcome-level gravity and omits a gravity filter from the MVP.

### S0 handoff and backend readiness

Start with the [HTTP contract](docs/contracts/API.md), [OpenAPI 3.1 document](docs/contracts/openapi.json), [storage contract](docs/contracts/STORAGE.md) and [RDF mapping](docs/contracts/RDF.md). The [fixture manifest](data/fixtures/s0/manifest.json) records exact source hashes, selected rows and pending review. These are development contracts and examples; backend services remain unimplemented.

| Issue | Contract readiness |
| --- | --- |
| B1 #16 | Health readiness, snapshot date and actual loaded counts defined. Verified experiment counts remain null. |
| B2 #17 | Storage identities, validation, idempotent updates and replacement-database checks defined. |
| B3 #18 | Search requests, matching evidence and pagination defined; ranking implementation/evaluation remains work. |
| B4 #19 | Source-row provenance and supported value/outcome RDF mapping defined; classification and unsupported mappings remain blocked. |
| B5 #20 | Study and evidence detail/list responses, IDs and missing states defined. |
| B6 #21 | File identity, search, filters, ordering, pagination and access states defined. |
| B7 #22 | Source-record envelopes defined; run filters, verified coverage counts and regions remain provisional. |
| B8 #23 | Shared offline fixtures and validator supplied; backend build/start/integration commands remain implementation work. |

Run `python docs/contracts/validate.py` offline with the existing `jsonschema` and `referencing` packages. See [validation commands and results](docs/contracts/API.md#validation) for scope and limitations. No dependencies or runtime endpoints are added by this handoff.


## Growth and Limits

The remote collection already exceeds 13 TB. Keep large experimental files with NASA and scale the catalog and extracted evidence independently:

- Process documents in batches and preserve source references.
- Reindex new or changed content using stable IDs, versions, and hashes.
- Paginate remote-file results instead of loading the complete catalog into the browser.
- Use structured queries for numerical tables.
- Expand ingestion and search infrastructure when measured throughput or latency requires it.

The MVP excludes live answer generation, simulation, predictive fire-risk scores, distance-based run ranking, OCR, video analysis, and a triple-store server. Embeddings are optional after the core workflow works and a reviewed evaluation shows that they improve keyword search. Modeling support consists of conditions, outcomes, coverage gaps, and source files for future models. The MVP does not include a validated predictive model.

## Official Resources

| Resource | Description |
| --- | --- |
| [PSI Data Repository: Combustion Science](https://psi.nasa.gov/physci/repo/search?q=combustion) | Primary source of combustion data for the application. |
| [NASA Combustion Science](https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/) | Background on most combustion investigations represented in PSI. |
| [NASA ScienceCasts: The Power of Studying Combustion on the ISS](https://www.youtube.com/watch?v=W1oXykoz9zg) | A 2018 introductory video about combustion research aboard the ISS. |
| [A Researcher’s Guide to International Space Station Combustion Science](https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/) | A 2015 review of combustion research conducted or planned aboard the ISS. |
| [Apollo 1](https://sma.nasa.gov/sma-disciplines/accllp/apollo-1) | The mission, fatal pre-launch fire, investigation, and lessons learned. |
| [Apollo 13](https://sma.nasa.gov/sma-disciplines/accllp/apollo-13) | The mission, in-flight oxygen tank explosion, investigation, and lessons learned. |
| [25 Years Ago: Fire Aboard Space Station Mir](https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/) | The 1997 Mir fire caused by an oxygen generator failure. |
| [Fireman’s Air Tanks](https://spinoff.nasa.gov/node/9582) | Spacesuit technology adapted to improve firefighters’ air tanks and breathing equipment. |
| [Fire Detector](https://spinoff.nasa.gov/node/9407) | Shuttle smoke detector technology that distinguishes smoke from dust to reduce nuisance alarms. |
| [New Technology for the Fire Attire](https://spinoff.nasa.gov/node/9918) | NASA spacesuit technology applied to firefighter clothing. |

<!-- PSI-INVENTORY:START -->
## Combustion Dataset Inventory

NASA PSI lists 24 combustion investigations with 60,866 files.
Their reported dataset sizes total 13.50 TB (13,496,771,103,733 bytes; 0 datasets have no reported total).
The current file listings sum to 13.47 TB (13,471,850,126,356 known bytes; 0 files have no reported size).
The inventory stores metadata locally; the separate table downloader retrieves selected small tabular files. Sizes below describe the full remote collection, not local downloads.

Titles, versions, file counts, and sizes come from PSI's API. Sizes use decimal units. Each inventory lists individual file sizes and preserves any difference between PSI's dataset total and file-size sum.

| Dataset | Investigation title | Version | Files | Reported dataset size | Listed file size sum | Reported bytes | Inventory |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [PSI-10](https://psi.nasa.gov/physci/repo/data/investigations/PSI-10) | Advanced Combustion via Microgravity Experiments / Flame Design | 1 | 3,807 | 2.18 TB | 2.18 TB | 2180435304347 | [Files](metadata-info/PSI-10.md) |
| [PSI-20](https://psi.nasa.gov/physci/repo/data/investigations/PSI-20) | Advanced Combustion via Microgravity Experiments - Burning Rate Emulator | 4 | 2,361 | 2.04 TB | 2.04 TB | 2035568427496 | [Files](metadata-info/PSI-20.md) |
| [PSI-21](https://psi.nasa.gov/physci/repo/data/investigations/PSI-21) | Advanced Combustion via Microgravity Experiments / Coflow Laminar Diffusion Flame | 4 | 4,134 | 2.01 TB | 2.00 TB | 2005536295241 | [Files](metadata-info/PSI-21.md) |
| [PSI-22](https://psi.nasa.gov/physci/repo/data/investigations/PSI-22) | Advanced Combustion via Microgravity Experiments Electric-Field Effects on Laminar Diffusion Flames | 7 | 2,578 | 950.21 GB | 950.07 GB | 950212491107 | [Files](metadata-info/PSI-22.md) |
| [PSI-23](https://psi.nasa.gov/physci/repo/data/investigations/PSI-23) | Advanced Combustion via Microgravity Experiments-Structure and Response of Spherical Diffusion Flames | 4 | 4,165 | 782.17 GB | 782.17 GB | 782172126062 | [Files](metadata-info/PSI-23.md) |
| [PSI-25](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25) | Burning and Suppression of Solids - II | 4 | 695 | 274.63 GB | 274.63 GB | 274631106141 | [Files](metadata-info/PSI-25.md) |
| [PSI-26](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26) | Burning and Suppression of Solids | 4 | 210 | 163.55 GB | 163.55 GB | 163551372412 | [Files](metadata-info/PSI-26.md) |
| [PSI-39](https://psi.nasa.gov/physci/repo/data/investigations/PSI-39) | Cool Flames Investigation | 4 | 2,812 | 718.89 GB | 718.89 GB | 718889568684 | [Files](metadata-info/PSI-39.md) |
| [PSI-47](https://psi.nasa.gov/physci/repo/data/investigations/PSI-47) | Dust and Aerosol Measurement Feasibility Test / Dust and Aerosol Measurement Feasibility Test-2 | 5 | 33 | 41.77 MB | 41.77 MB | 41765333 | [Files](metadata-info/PSI-47.md) |
| [PSI-60](https://psi.nasa.gov/physci/repo/data/investigations/PSI-60) | Computational and Experimental Analysis of SPICE Data Sets | 1 | 1 | 7.74 kB | 7.74 kB | 7743 | [Files](metadata-info/PSI-60.md) |
| [PSI-62](https://psi.nasa.gov/physci/repo/data/investigations/PSI-62) | Concurrent Flame Spread Modeling using Flamelet Generated Manifolds in Microgravity with Comparison to BASS Experiments using Two-Color Tomography | 1 | 1 | 9.69 kB | 9.69 kB | 9694 | [Files](metadata-info/PSI-62.md) |
| [PSI-68](https://psi.nasa.gov/physci/repo/data/investigations/PSI-68) | Flame Extinguishment Experiment - 2 | 6 | 10,077 | 1.22 TB | 1.22 TB | 1224752113090 | [Files](metadata-info/PSI-68.md) |
| [PSI-69](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69) | Flame Extinguishment Experiment | 5 | 6,453 | 923.83 GB | 921.40 GB | 923832535657 | [Files](metadata-info/PSI-69.md) |
| [PSI-98](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98) | Spacecraft Fire Safety Experiment-I | 4 | 76 | 12.25 GB | 12.25 GB | 12250600201 | [Files](metadata-info/PSI-98.md) |
| [PSI-99](https://psi.nasa.gov/physci/repo/data/investigations/PSI-99) | Spacecraft Fire Experiment-II | 5 | 214 | 16.93 GB | 16.83 GB | 16931016137 | [Files](metadata-info/PSI-99.md) |
| [PSI-100](https://psi.nasa.gov/physci/repo/data/investigations/PSI-100) | Spacecraft Fire Experiment-III | 4 | 87 | 35.21 GB | 35.21 GB | 35210765052 | [Files](metadata-info/PSI-100.md) |
| [PSI-101](https://psi.nasa.gov/physci/repo/data/investigations/PSI-101) | Smoke Aerosol Measurement Experiment-Reflight | 4 | 344 | 6.31 GB | 6.31 GB | 6308124750 | [Files](metadata-info/PSI-101.md) |
| [PSI-102](https://psi.nasa.gov/physci/repo/data/investigations/PSI-102) | Smoke and Aerosol Measurement Experiment | 4 | 101 | 657.61 MB | 657.61 MB | 657608178 | [Files](metadata-info/PSI-102.md) |
| [PSI-106](https://psi.nasa.gov/physci/repo/data/investigations/PSI-106) | Structure and Liftoff In Combustion Experiment | 3 | 18,707 | 72.91 GB | 60.79 GB | 72914598688 | [Files](metadata-info/PSI-106.md) |
| [PSI-107](https://psi.nasa.gov/physci/repo/data/investigations/PSI-107) | Smoke Point In Co-flow Experiment | 4 | 188 | 6.95 GB | 6.95 GB | 6946864573 | [Files](metadata-info/PSI-107.md) |
| [PSI-115](https://psi.nasa.gov/physci/repo/data/investigations/PSI-115) | Utilization of the Smoke Aerosol Measurement Experiment Data for Advanced Modeling and Simulation of Smoke Generation in Micro-Gravity | 3 | 47 | 264.40 MB | 264.40 MB | 264404901 | [Files](metadata-info/PSI-115.md) |
| [PSI-117](https://psi.nasa.gov/physci/repo/data/investigations/PSI-117) | Effect of External Thermo-Convective Perturbation on Cool Flame Dynamics: A Multidimensional Multi-Physics CFD Analysis | 2 | 16 | 70.82 MB | 70.82 MB | 70820870 | [Files](metadata-info/PSI-117.md) |
| [PSI-142](https://psi.nasa.gov/physci/repo/data/investigations/PSI-142) | Quantitative Studies of Cool Flame Transitions at Radiation / Stretch Extinction Using Counterflow Flames | 2 | 3 | 748.12 kB | 748.12 kB | 748117 | [Files](metadata-info/PSI-142.md) |
| [PSI-159](https://psi.nasa.gov/physci/repo/data/investigations/PSI-159) | Advanced Combustion via Microgravity Experiments / Cool Flames Investigation with Gases | 1 | 3,756 | 2.09 TB | 2.09 TB | 2085592429259 | [Files](metadata-info/PSI-159.md) |

### Refresh metadata

Requires Python 3.10+; no additional packages.

```bash
python scripts/download_metadata.py
```

The script downloads raw investigation metadata and file listings for the full Combustion Science research area. It preserves response bodies in `res/`, records source URLs and SHA-256 hashes, writes one inventory per dataset in `metadata-info/`, and saves a machine-readable inventory in `res/catalog/inventory.json`. It never downloads experimental files or extracts archives.

```text
res/catalog/                 Raw search pages and discovery records
res/PSI-<id>/metadata.json    Raw investigation metadata
res/PSI-<id>/files.json       Raw file listing
res/PSI-<id>/provenance.json  Retrieval dates, requests, and hashes
metadata-info/PSI-<id>.md     Dataset details and per-file sizes
```

To rebuild inventories from saved metadata without network access:

```bash
python scripts/download_metadata.py --offline
```

The script does not edit the README. The dataset table is a snapshot and must be refreshed manually.

<!-- PSI-INVENTORY:END -->

### Fetch experimental tables

After refreshing metadata and inventories, download all files categorized as `Experimental table` and the BASS test-matrix spreadsheets:

```bash
python scripts/fetch_experimental_tables.py
```

The script saves source tables to `res/experimental-tables/` by default. Use `--out <directory>` to choose another location. Normalization, flow calibration, report extraction, and graph construction remain planned work.
