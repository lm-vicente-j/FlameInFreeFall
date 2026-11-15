# MVP Implementation Plan

## Goal and Architecture

Build an interactive research explorer with two layers. Reviewed research cards summarize, rank, compare, and interpret NASA PSI combustion investigations with source evidence. A run-level condition explorer shows which test runs cover a given atmosphere, airflow, and material, what each recorded, and where PSI has no runs. The rationale and data findings are in [docs/APPROACH.md](docs/APPROACH.md).

```text
Investigation layer                         Run layer
PSI metadata + selected documents           PSI experimental tables (all 22)
    -> evidence extraction                      -> parsing, alias mapping, reviewed LLM extraction of free text
    -> skill-generated and reviewed             -> normalized run records with provenance
       research-card JSON                       -> RDF run graph (SOSA/SSN, QUDT, PROV-O + project vocabulary)
    -> SQLite catalog and keyword index         -> in-memory graph queried with SPARQL
                   \                             /
                    -> dashboard: cards, comparisons, cited insights, condition explorer, coverage gaps
```

Use Python, Flask, SQLite FTS5/BM25, rdflib, pypdf, HTML, CSS, and vanilla JavaScript. rdflib holds the run graph in memory and answers SPARQL queries without a triple-store server. Generate research cards and free-text run extractions with a skill during preparation, and review them before import. The application searches and displays prepared data without external AI APIs or runtime answer generation.

The repository currently provides metadata collection, inventories, and `scripts/fetch_experimental_tables.py`, which downloads every experimental table and the BASS test matrices (about 230 KB). The dashboard, sample downloader, evidence pipeline, research-card skill, run normalization, run graph, and search service remain to be implemented.

Deliverables:

- Searchable coverage of all 24 investigations in the saved snapshot.
- The complete saved remote-file catalog with pagination.
- Reviewed research cards and supporting evidence.
- Comparisons between two investigations.
- Documented findings and safety implications for BASS-II, Saffire-I, SAME-R, and FLEX.
- A run graph containing every row of the 22 experimental tables, each traceable to its source file, row, and original text.
- Normalized conditions and outcomes for FLEX, Saffire-II, BASS, and BASS-II runs.
- A condition explorer with an oxygen-versus-pressure coverage map, a filterable runs table, gap states, and links to source files.
- Updated documentation and a reproducible local demonstration.

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
- Evidence: stable ID, investigation, source URL, file/version reference, exact excerpt, and metadata-field or PDF-page locator.
- File record: investigation, remote ID, filename, category, extension, version, bytes, and access status.
- Run record: stable ID, investigation, fuel class, material, geometry, O2 percent, pressure in kPa, minimum and maximum flow in cm/s, flow direction, diluent, outcome type, outcome value and unit, and provenance. Provenance records the source file, row, original text, extraction method (parsed, mapped, llm, or manual), and review status.
- RDF vocabulary: model each run as a SOSA/SSN observation, units with QUDT, and provenance with PROV-O. The project vocabulary adds only the material hierarchy, fuel classes, and outcome types. Freeze it in hours 0–2.
- Preserve scientific units and source references. Unknown attributes remain unknown.

Every generated summary and claim must reference supplied evidence. Metadata describing a hypothesis or expected impact must not be presented as a measured result. Values extracted by an LLM must be reviewed before import and must keep their original text.

## Implementation Workstreams

### `alan-pv`: Data Pipeline

- Preserve the existing metadata collector and its separation from README editing.
- Implement a sample downloader that selects files from saved PSI metadata, records source references and hashes, and enforces a 250 MB total download budget. Do not download archives or experimental videos.
- Select up to 20 readable PDFs across the four core investigations, targeting three per investigation. Prioritize scientific reports and experiment documentation.
- Extract PDFs sequentially in subprocesses with a 60-second per-file timeout. Preserve page boundaries and record failures. Skip OCR and unreadable documents.
- Build one evidence packet per investigation, combining scientific metadata and available extracted passages.
- Implement a reusable repository skill that produces research-card JSON from one evidence packet. Invoke it explicitly during preparation.
- Implement validation for required fields, claim types, evidence references, and exact supporting excerpts. Reject unsupported numerical claims.
- Generate and review 24 cards. Clearly identify metadata-only coverage.
- For each core investigation, include at least one documented finding, its experimental conditions, a supported safety implication, and citations.
- Identify measurements, conditions, and remote source files useful for future predictive modeling. Do not claim that a predictive model has been implemented or validated.
- Normalize all 22 experimental tables into run records. Parse numeric columns directly and convert units. Load columns that cannot be normalized yet as original text.
- Build reviewed alias dictionaries for short repeated text, such as material names, oxygen ranges, flow sweeps, and Saffire-II burn results. An LLM may propose mappings; a person approves each one.
- Extract outcomes from the BASS "Test Observations and Anomalies" column with an LLM and a fixed JSON schema that quotes the source text. Review every record.
- Convert BASS and BASS-II fan readings to velocity using `Fan calibration data.xlsx`. Record flow sweeps as a minimum and maximum.
- Normalize FLEX and Saffire-II first, since they need no LLM extraction, then BASS and BASS-II.

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
- Provide repeatable commands to build the catalog and run graph and to start the application. Lock dependencies after the first working installation.
- Optional, after the core workflow works: add EmbeddingGemma embeddings to FTS5 for hybrid search over evidence passages and run notes. Compute passage embeddings during preparation and only the query embedding at runtime, locally. Adopt it only if it beats FTS5 on the reviewed search questions, and record the comparison.

| Interface | Behavior |
| --- | --- |
| `GET /api/studies` | Search/filter studies; return ranked cards and matching evidence |
| `GET /api/studies/<accession>` | Return a complete card and comparison attributes |
| `GET /api/studies/<accession>/files` | Return paginated remote-file metadata |
| `GET /api/evidence/<id>` | Return an excerpt, source locator, and source URL |
| `GET /api/runs` | Filter runs by fuel class, material, O2, pressure, flow, and outcome; return conditions, outcomes, and provenance |
| `GET /api/runs/<id>` | Return one run with its original text, extraction method, review status, and source file links |
| `GET /api/coverage` | Return run counts by condition region for the current filters, including empty regions |
| `GET /api/health` | Return readiness, snapshot date, and indexed study and run counts |

### `EmmanuelRamiro23`: Dashboard

- Implement search, prevention/detection/suppression filters, ranked cards, and study-detail views.
- Show prepared summaries and the evidence explaining each match. Relevance scores must not be presented as fire-risk scores.
- Implement side-by-side comparison of two investigations. Display objectives, findings, fuels, conditions, measurements, limitations, and modeling resources when supported.
- Implement an expandable evidence viewer with source links and page/field references.
- Implement the paginated remote-file browser and research-card JSON export.
- Implement the condition explorer: an oxygen-versus-pressure coverage map marking NASA's three crew atmospheres (14.7 psia with 21% O2, 10.2 psia with 26.5%, and 8.2 psia with 34%), filters for fuel class, material, flow, and outcome, and a sortable runs table.
- Show a clear state when no run covers a scenario, stating that it means "not in PSI", not "never studied".
- Implement a run-detail view with conditions, outcome, original source text, extraction method, review status, and source file links. Distinguish LLM-extracted values from parsed values.
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

Stop document collection at hour 12. Continue with available evidence and explicitly identify unmet evidence requirements. Metadata coverage must still include all 24 investigations. Stop adding investigations to deep run normalization at hour 24. The remaining tables still load with their parsed columns and original text.

## Acceptance and Testing

- All 24 investigations and the saved remote-file catalog are browsable.
- Every generated summary and claim references valid evidence with a source locator.
- Each core investigation has one verified finding, its conditions, and a supported safety implication.
- At least ten of twelve reviewed search questions return a relevant investigation in the top three. Establish expected matches before evaluating ranking.
- Three unsupported questions return no supported match rather than an invented explanation.
- Comparisons preserve unknown values, units, and differences in experimental conditions.
- Every row of the 22 experimental tables appears in the run graph with its source file, row, and original text.
- FLEX, Saffire-II, BASS, and BASS-II runs have normalized O2, pressure, flow where recorded, and outcome, or an explicit unknown.
- Every LLM-extracted value is reviewed and displays its original text.
- The coverage map agrees with the source tables, for example that no solid-fuel run exceeds 22.2% O2 or falls below about 0.97 atm.
- Repeated imports produce no duplicates; changed records update correctly.
- Download failures, unreadable PDFs, invalid cards, invalid run records, unknown IDs, and backend errors produce clear states.
- Startup, search, comparison, evidence viewing, and the condition explorer work without network access after preparation. Opening external source links requires network access.
- Search and run queries target a 95th-percentile response below one second across 30 representative queries after startup.
- The metadata collector never edits the README.
- Each collaborator supplies tests for their subsystem and records test commands and results in the handoff.

Run tests locally under the existing `test_*` ignore rule. Commit reproducible input fixtures where needed; do not change the ignore rule as part of this MVP.

## Growth and Boundaries

Keep large experimental files with NASA. Scale the catalog and extracted passage index independently of the size of remote archives and videos. Retain stable identifiers, versions, and hashes to support incremental refreshes. Process documents in batches and use structured queries for numerical tables.

The MVP processes every experimental table but extracts report text only from a sample, because human review time, not storage, is the limit. The run graph uses public W3C vocabularies, so it can be exported as Turtle or JSON-LD and extended with other datasets.

Defaults: English interface, local single-user demonstration, and existing assistant access for preparation-time skill execution. Preparation-time AI execution is separate from the offline application; retain generated cards, run extractions, and evidence for independent operation.

Exclude fire simulation, predictive risk scores, distance-based relevance scores for runs, runtime answer generation, video analysis, OCR, a triple-store server, accounts, and public hosting from this release. Embeddings are optional, as described in the backend workstream.
