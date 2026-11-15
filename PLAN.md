# MVP Implementation Plan

## Goal and Architecture

Build a research explorer with two layers: reviewed cards for NASA PSI combustion investigations and a condition explorer for individual runs. The cards support search, ranking, comparison, and interpretation with cited evidence. The condition explorer shows which runs cover an atmosphere, airflow, and material, their recorded outcomes, and gaps in the saved PSI tables. See [APPROACH.md](docs/APPROACH.md) for the rationale and data findings.

APPROACH.md remains a proposal under review. This plan includes its condition explorer alongside the planned investigation layer. The accepted normalization priorities, gravity display, report scope, and external-coverage limits are recorded under [Accepted Decisions](#accepted-decisions). Flow-sweep behavior and cross-hardware comparison rules still require agreement.

```text
Investigation layer                         Run layer
PSI metadata + selected documents           All 22 experimental tables + BASS test matrices
    -> evidence extraction                      -> parsing, alias mapping, reviewed LLM extraction of free text
    -> skill-generated and reviewed             -> normalized run records with provenance
       research-card JSON                       -> RDF run graph (SOSA/SSN, QUDT, PROV-O + project vocabulary)
    -> SQLite catalog and keyword index         -> in-memory graph queried with SPARQL
                   \                             /
                    -> dashboard: cards, comparisons, cited insights, condition explorer, coverage gaps
```

Use Python, Flask, SQLite FTS5/BM25, rdflib, pypdf, HTML, CSS, and vanilla JavaScript. rdflib holds the run graph in memory and answers SPARQL queries without a triple-store server. Use a skill to generate research cards and extract run observations from free text during preparation. Validate records before import. Development records may retain clearly labeled pending proposals; review them before using them as scientific results or verified coverage. The application searches and displays prepared data without external AI APIs or runtime answer generation.

The repository provides metadata collection, inventories, and `scripts/fetch_experimental_tables.py`, which downloads every experimental table and the BASS test matrices. The 2026-11-14 review covers 22 CSVs totaling about 230 KB and 2,010 non-empty rows, plus the spreadsheets. These rows include individual runs, fuel ranges, session summaries, and notes.

The dashboard, sample downloader, evidence pipeline, research-card skill, run normalization, run graph, and search service remain to be implemented.

Deliverables:

- Searchable coverage of all 24 investigations in the saved snapshot.
- The complete saved remote-file catalog with pagination.
- Reviewed research cards and supporting evidence.
- Comparisons between two investigations.
- Documented findings and safety implications for BASS-II, Saffire-I, SAME-R, and FLEX.
- A graph preserving every non-empty row from the 22 experimental tables with its source file, row number, and original text. Coverage counts distinguish individual runs from ranges, session summaries, and notes.
- Normalized conditions and outcomes for FLEX, Saffire-II, BASS, and BASS-II runs.
- A condition explorer with an oxygen-versus-pressure coverage map, a filterable runs table, gap states, and links to source files.
- Updated documentation and a reproducible local demonstration.

## Data Basis and Limits

- FLEX and Saffire-II provide usable tabular outcomes. Saffire-II records both 1 g and microgravity results. Preserve gravity per outcome and label the normal-gravity results as "1 g ground test"; the MVP has no gravity filter.
- BASS's as-run XLSX supplies conditions and free-text observations missing from its CSV. BASS-II records extinction and blowoff in flow-column text rather than a dedicated outcome column.
- BASS and BASS-II flow values are instrument display readings. Physical velocities require `Fan calibration data.xlsx`, matched by test date and number of flow restrictors. Most BASS-II runs are flow sweeps.
- SAME-R has no particle-size outcomes in its table. Use the selected scientific reports for missing outcomes. The sampled BASS-II ProofSheet contains camera metadata and no outcomes; do not collect the remaining 124 ProofSheets.
- The initial review found no solid-fuel run above 22.2% O2 or below about 0.97 atm in these tables. FLEX's reduced-pressure, oxygen-enriched droplet runs do not fill the solid-fuel gap. ACME BRE describes exploration atmospheres in its objectives, but its table contains session summaries.
- PSI-60, PSI-62, PSI-115, and PSI-117 are modeling-only investigations without experimental tables. Retain their investigation cards without inventing runs.
- Coverage statements apply to the saved PSI tables and current filters. Saffire-IV–VI and SoFIE coverage outside PSI remains explicitly unverified and is outside the MVP verification scope. Do not infer that this research is absent or include it in coverage claims without supporting evidence.

## Coding Ownership

| Collaborator | Implementation ownership | Required code deliverables |
| --- | --- | --- |
| `alan-pv` | Data ingestion, research-card preparation, and run normalization | Sample downloader, PDF extractor, evidence-packet builder, card validator, research-card skill, table normalizer, alias dictionaries, free-text run extraction |
| `lm-vicente-j` | Storage, search, run graph, and backend | SQLite importer, FTS5 ranking, RDF vocabulary, run-graph loader, SPARQL queries, query handling, HTTP endpoints, integration commands |
| `EmmanuelRamiro23` | Dashboard and application workflows | Search interface, filters, study details, comparison view, evidence viewer, file browser, condition explorer, runs table, JSON export |

Each collaborator implements and tests their subsystem. `lm-vicente-j` coordinates integration. Scientific review and presentation work are shared after the first integrated build.

Agree on the JSON, HTTP, and RDF vocabulary contracts in hours 0–2. Use the same two-investigation fixture and a run fixture covering FLEX and Saffire-II to develop independently.

## Shared Contracts

- Research card: accession, source version, title, cited summary, safety categories, comparison attributes, claims, limitations, and modeling resources.
- Claim: text, evidence IDs, and type—objective, hypothesis, reported observation, or potential application.
- Evidence: stable ID, investigation, source URL, file/version reference, exact excerpt, and metadata-field, PDF-page, or experimental-table-row locator. A table locator retains the source file/version, hash, row number, and corresponding run-record ID.
- File record: investigation, remote ID, filename, category, extension, version, bytes, and access status.
- Run record: stable ID, investigation, fuel class, material, geometry, O2 percent, pressure in kPa, minimum and maximum flow in cm/s, flow direction, diluent, outcome type, outcome value and unit, and provenance. Preserve initial/final conditions, gravity on each outcome (`microgravity` or `normal`), and whether a source row describes a run, range, session, or note. Provenance includes the source file, row number, original text, extraction method (parsed, mapped, llm, or manual), and review status. Include source-file links and supporting report evidence IDs when available.
- RDF vocabulary: model each run as a SOSA/SSN observation, units with QUDT, and provenance with PROV-O. The project vocabulary adds only the material hierarchy, fuel classes, and outcome types. Freeze it in hours 0–2.
- Preserve scientific units and source references. Unknown attributes remain unknown.

Every generated summary and claim must reference supplied evidence. Label hypotheses and expected impacts as such. Retain the original text of every LLM-extracted value. Pending proposals may remain in development records and views, clearly labeled as pending; they cannot support reviewed findings or verified coverage. Review them before accepting them as scientific results. Show the authors' conclusions only, including cited safety implications.

## Implementation Workstreams

### `alan-pv`: Data Pipeline

- Preserve the existing metadata collector and its separation from README editing.
- Implement a sample downloader that selects files from saved PSI metadata, records source references and hashes, and enforces a 250 MB total download budget. Do not download archives or experimental videos.
- Use the existing sample of 12 PDFs, three per core investigation, prioritizing scientific reports and experiment documentation. Eleven have a text layer. Keep the 250 MB total budget and maximum of 20 PDFs; the maximum is not a collection target. Do not expand collection to the remaining BASS-II ProofSheets.
- Extract PDFs sequentially in subprocesses with a 60-second per-file timeout. Preserve page boundaries and record failures. Skip OCR and unreadable documents.
- Build one evidence packet per investigation, combining scientific metadata, available extracted passages, and citable experimental-table rows. For Saffire-I, use its official table for measured burn times; the available paper describes pre-flight plans.
- Record the missing Saffire offgassing-strategy PDF as an HTTP 404 failure and the Saffire-I thermocouple-placement PDF as having no text layer. Do not use OCR. Cards must state unmet evidence requirements as limitations, and unsupported outcomes remain unknown.
- Implement a reusable repository skill that produces research-card JSON from one evidence packet. Invoke it explicitly during preparation.
- Implement validation for required fields, claim types, evidence references, and exact supporting excerpts. Reject unsupported numerical claims.
- Generate and review 24 cards. Clearly identify metadata-only coverage.
- For each core investigation, include at least one documented finding, its experimental conditions, a supported safety implication, and citations.
- Identify measurements, conditions, and remote source files useful for future predictive modeling. Do not claim that a predictive model has been implemented or validated.
- Normalize all 22 experimental tables and the BASS as-run XLSX. Parse numeric columns directly and convert units. Preserve non-run rows and unnormalized columns as source records without counting them as individual tests.
- Flag the data-quality issues in APPROACH.md: empty CFI-G rows, Saffire/SAME notes and references to earlier conditions, repeated SPICE rows, FLEX test 114's invalid 0 mmHg pressure, and ACME BRE's `3400%` and `2100%` oxygen entries. Preserve source values and exclude invalid readings from valid-condition plots. Record any reviewed corrections.
- Build reviewed alias dictionaries for short repeated text, such as material names, oxygen ranges, flow sweeps, and Saffire-II burn results. An LLM may propose mappings; a person approves each one.
- Extract outcomes from the BASS "Test Observations and Anomalies" column with an LLM and a fixed JSON schema that quotes the source text. Review every record before accepting its results. If review time runs out, retain the proposals as pending and show that status; do not present them as confirmed observations.
- Extract BASS-II extinction and blowoff observations from flow-column text with supporting excerpts and review. Keep outcomes unknown when neither the table nor a processed report supports them.
- Locate and verify `Fan calibration data.xlsx` before converting BASS and BASS-II fan readings to velocity. Match calibration by test date and number of flow restrictors. Retain raw readings and leave velocity unknown when no valid conversion is available. This plan uses a minimum and maximum for flow sweeps, pending team review.
- Link runs to experimental files using identifiers such as BASS-II sample and test numbers, and to cited report passages when available. Preserve ambiguous matches for review.
- Normalize FLEX and Saffire-II first, since they need no LLM extraction, then BASS and BASS-II. The minimum preparation target is recorded conditions and outcomes for these four investigations, normalized where supported and explicitly unknown otherwise. Preserve the remaining tables row by row with original text and quality flags; conditions without a supported normalizer stay unknown.

### `lm-vicente-j`: Catalog and Backend

- Implement separate SQLite tables for investigations, cards, evidence, and remote files.
- Import validated records using stable IDs, source versions, and hashes. Repeated imports must not create duplicates.
- Build and validate a replacement database before switching from the last valid version.
- Implement weighted FTS5/BM25 search, prioritizing titles and acronyms. Return matching evidence alongside results.
- Add reviewed synonym mappings for suppression/extinguishment and detection/smoke sensing.
- Keep scientific search separate from filename search. Implement file pagination and category/extension filters.
- Interpret ordinary input as search terms rather than raw FTS syntax. Use parameterized queries and return an explicit no-match state when appropriate.
- Define the RDF vocabulary from SOSA/SSN, QUDT, PROV-O, and the project terms. Validate run records against it before loading.
- Load normalized run records into an in-memory rdflib graph at startup. Keep SQLite for cards, evidence, and files.
- Implement run filtering and coverage as predefined, parameterized SPARQL queries. Never pass user input as raw SPARQL.
- Preserve outcome-level gravity in API responses. Do not add a gravity query parameter to the MVP.
- Provide repeatable commands to build the catalog and run graph and to start the application. Lock dependencies after the first working installation.
- Optional, after the core workflow works: add EmbeddingGemma embeddings to FTS5 for hybrid search over evidence passages and run notes. Compute passage embeddings during preparation and only the query embedding at runtime, locally. Adopt it only if it beats FTS5 on the reviewed search questions, and record the comparison.

| Interface | Behavior |
| --- | --- |
| `GET /api/studies` | Search/filter studies; return ranked cards and matching evidence |
| `GET /api/studies/<accession>` | Return a complete card and comparison attributes |
| `GET /api/studies/<accession>/files` | Return paginated remote-file metadata |
| `GET /api/evidence/<id>` | Return an excerpt, source locator, and source URL |
| `GET /api/runs` | Filter runs by fuel class, material, geometry, flow direction, O2, pressure, flow, and outcome; return conditions, outcomes, and provenance |
| `GET /api/runs/<id>` | Return one run with its original text, extraction method, review status, and source file links |
| `GET /api/coverage` | Return run counts by condition region for the current filters, including empty regions |
| `GET /api/health` | Return readiness, snapshot date, and indexed study and run counts |

### `EmmanuelRamiro23`: Dashboard

- Implement search, prevention/detection/suppression filters, ranked cards, and study-detail views.
- Show prepared summaries and the evidence explaining each match. Relevance scores must not be presented as fire-risk scores.
- Implement side-by-side comparison of two investigations. Display objectives, findings, fuels, conditions, measurements, limitations, and modeling resources when supported.
- Implement an expandable evidence viewer with source links and page/field references.
- Implement the paginated remote-file browser and research-card JSON export.
- Implement the condition explorer: filter first by fuel class, material, geometry, and flow direction, then explore oxygen, pressure, airflow, and outcome. Show an oxygen-versus-pressure coverage map marking NASA's three crew atmospheres (14.7 psia with 21% O2, 10.2 psia with 26.5%, and 8.2 psia with 34%) alongside a sortable runs table.
- Show "not in PSI" when no run covers the displayed filters and condition ranges. Explain that the gap does not establish whether a scenario has been studied elsewhere, whether it is safe, or what would happen.
- Preserve differences in hardware, fuel, and flow definitions in comparisons. Show unknown or uncalibrated conditions explicitly; avoid ranking runs by a normalized distance to the scenario.
- Implement a run-detail view with conditions, outcome, original source text, extraction method, review status, and source file links. Distinguish LLM-extracted values from parsed values.
- Show Saffire-II's normal-gravity outcomes with a visible "1 g ground test" label alongside the microgravity results. Do not add a gravity filter. Display unreviewed proposals as pending, never as confirmed results.
- Display loading, empty, missing-evidence, and backend-error states.
- Show the snapshot date and distinguish cataloged files from documents whose contents were processed.
- Label AI summaries as prepared content. Do not present the interface as a live generative chatbot.
- Implement using HTML, CSS, and vanilla JavaScript served by Flask; avoid a separate frontend build system. Draw the coverage map as SVG or with a vendored chart library so it works offline.

## Schedule and Integration

| Hours | `alan-pv` | `lm-vicente-j` | `EmmanuelRamiro23` | Checkpoint |
| --- | --- | --- | --- | --- |
| 0–2 | Define evidence/card and run fixtures | Define database, RDF vocabulary, and API contracts | Define screen interactions, including the condition explorer | Shared contracts and vocabulary frozen |
| 2–12 | Code downloader, extraction, and packet builder; normalize FLEX and Saffire-II | Code importer, search endpoints, and run-graph loader | Code interface and coverage map against fixtures | Search-to-detail and coverage map run |
| 12–24 | Code validator; generate reviewed cards; normalize BASS and BASS-II with reviewed free-text extraction | Complete evidence, file, run, and coverage endpoints | Integrate comparisons, evidence, file browser, runs table, and gap states | Complete workflow with real data |
| 24–36 | Test extraction; audit findings and run records | Test ranking, SPARQL queries, imports, and failures; optional embeddings comparison | Test integrated workflows and fix interface issues | Feature freeze |
| 36–44 | Fix pipeline defects; review citations | Benchmark and package startup | Polish demonstration and export workflow | Release candidate |
| 44–48 | Final evidence review | Resolve release blockers | Complete demonstration and submission | Submit with contingency time |

Stop document collection at hour 12 and use the accepted 12-PDF sample. Continue with available evidence and list unmet evidence requirements. Metadata coverage must still include all 24 investigations. At hour 24, stop adding investigations for detailed run normalization. Preserve the remaining tables with their original text, quality flags, and any supported parsed values. If BASS/BASS-II review cannot finish, retain the proposals as pending and leave the corresponding reviewed results unknown.

## Acceptance and Testing

- All 24 investigations and the saved remote-file catalog are browsable.
- Every generated summary and claim references valid evidence with a source locator.
- Each core investigation has one verified finding, its conditions, and a supported safety implication.
- At least ten of twelve reviewed search questions return a relevant investigation in the top three. Establish expected matches before evaluating ranking.
- Three unsupported questions return no supported match rather than an invented explanation.
- Comparisons preserve unknown values, units, and differences in experimental conditions.
- Every non-empty row of the 22 experimental tables is preserved with its source file, row, and original text. Coverage counts distinguish individual runs from ranges, sessions, notes, and duplicate records; empty rows do not become runs.
- FLEX, Saffire-II, BASS, and BASS-II runs have normalized O2, pressure, flow where recorded, and outcome, or an explicit unknown.
- Every LLM-extracted value used as a scientific result is reviewed and displays its original text. Pending proposals remain visibly pending and do not support reviewed findings or verified coverage.
- Gravity is retained per outcome. Saffire-II's normal-gravity results display "1 g ground test"; the MVP exposes no gravity filter or query parameter.
- Categorical filters include geometry and flow direction. The coverage map agrees with the reviewed source tables, including the initial finding that no solid-fuel run exceeds 22.2% O2 or falls below about 0.97 atm. Missing conditions remain unknown.
- Invalid pressure/oxygen readings are flagged and excluded from valid-condition plots. Raw fan readings are never displayed as cm/s without a matching calibration, and sweeps are not presented as single measured settings.
- Run details link to matching source files and available report evidence. Unsupported outcomes remain unknown. Each displayed conclusion identifies its source authors.
- Repeated imports produce no duplicates; changed records update correctly.
- Download failures, unreadable PDFs, invalid cards, invalid run records, unknown IDs, and backend errors produce clear states.
- Startup, search, comparison, evidence viewing, and the condition explorer work without network access after preparation. Opening external source links requires network access.
- Search and run queries target a 95th-percentile response below one second across 30 representative queries after startup.
- The metadata collector never edits the README.
- Each collaborator supplies tests for their subsystem and records test commands and results in the handoff.
- Missing or unreadable source documents remain explicit failures or limitations. Coverage and gap messages apply only to the saved PSI snapshot; Saffire-IV–VI and SoFIE coverage outside PSI is labeled unverified.

Run tests locally under the existing `test_*` ignore rule. Commit reproducible input fixtures where needed; do not change the ignore rule as part of this MVP.

## Growth and Boundaries

### Accepted Decisions

The following proposals are accepted for the MVP as of 2026-11-15. This records scope decisions; scientific review, implementation checks, and PR integration remain separate requirements.

| Issue and proposal | Accepted decision | Rationale and fallback |
| --- | --- | --- |
| [D1 #32: normalization priorities](https://github.com/lm-vicente-j/FlameInFreeFall/issues/32#issuecomment-6899222053) | Prioritize FLEX and Saffire-II, then BASS and BASS-II. Prepare recorded conditions and outcomes for these four investigations, preserving the other tables row by row. | FLEX and Saffire-II need no LLM extraction. BASS/BASS-II require more review. Keep unreviewed proposals pending if time runs out; unsupported or unreviewed results remain unknown in reviewed output. |
| [D4 #35: gravity](https://github.com/lm-vicente-j/FlameInFreeFall/issues/35#issuecomment-6899222696) | Preserve gravity per outcome and omit a gravity filter from the MVP. Label Saffire-II normal-gravity outcomes "1 g ground test". | The recorded 1 g comparisons are outcomes paired with microgravity results, so a run filter would mainly hide comparison results. Preserve both labels and values. |
| [D5 #36: report scope](https://github.com/lm-vicente-j/FlameInFreeFall/issues/36#issuecomment-6899223058) | Use the existing 12-PDF sample and citable experimental-table rows. Do not collect the remaining 124 BASS-II ProofSheets. Keep the 250 MB budget, 20-PDF maximum, hour-12 cutoff, and no-OCR rule. | The sampled ProofSheet contains camera metadata, not outcomes. Record download failures and missing text layers. Use table evidence where supported, state missing evidence as a limitation, and leave unsupported outcomes unknown. Collection/extraction remains Alan's responsibility; scientific review remains shared. |
| [D6 #37: research outside PSI](https://github.com/lm-vicente-j/FlameInFreeFall/issues/37#issuecomment-6899223409) | Keep Saffire-IV–VI and SoFIE coverage outside PSI explicitly unverified. Do not expand the MVP verification scope to that research. | The saved PSI snapshot is the evidence baseline. Any later claim about wider coverage requires a cited source; a gap in PSI does not establish a gap in all NASA research. |

### Questions for Team Review

These decisions remain open:

- [D2 #33: flow sweeps](https://github.com/lm-vicente-j/FlameInFreeFall/issues/33): the current proposal uses one range per run. Agree on range versus supported steps, unknown endpoints, overlap filtering, and display. Confirm the applicability of the 2014 calibration before applying it to BASS's 2012–2013 readings; unsupported conversions remain unknown.
- [D3 #34: cross-hardware comparisons](https://github.com/lm-vicente-j/FlameInFreeFall/issues/34): agree which fuel, geometry, hardware, and flow definitions permit comparison, and how incompatible or unknown conditions appear.

Accepting D1, D4, D5, and D6 does not resolve D2 or D3, approve aliases or LLM extractions, or complete the shared schema/fixture agreement in S0 #6. Implementation and provenance defects tracked in #42 remain follow-up work.

### Scope

Keep large experimental files with NASA. Scale the catalog and extracted passage index independently of the size of remote archives and videos. Retain stable identifiers, versions, and hashes to support incremental refreshes. Process documents in batches and use structured queries for numerical tables.

The MVP processes every experimental table but extracts report text only from a sample, because human review time, not storage, is the limit. The run graph uses public W3C vocabularies, so it can be exported as Turtle or JSON-LD and extended with other datasets.

Defaults: English interface, local single-user demonstration, and existing assistant access for preparation-time skill execution. Preparation-time AI execution is separate from the offline application; retain generated cards, run extractions, and evidence for independent operation.

Exclude fire simulation, predictive risk scores, distance-based relevance scores for runs, runtime answer generation, video analysis, OCR, a triple-store server, accounts, and public hosting from this release. Embeddings are optional, as described in the backend workstream.
