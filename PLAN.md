# MVP Implementation Plan

## Goal and Architecture

Build an interactive research explorer that summarizes, ranks, compares, and interprets NASA PSI combustion investigations through reviewed research cards with source evidence.

```text
PSI metadata + selected documents
    -> evidence extraction
    -> skill-generated and reviewed research-card JSON
    -> SQLite catalog and keyword index
    -> dashboard, comparisons, and cited insights
```

Use Python, Flask, SQLite FTS5/BM25, pypdf, HTML, CSS, and vanilla JavaScript. Generate research cards with a skill during preparation. The application searches and displays those cards without external AI APIs or runtime model inference.

The repository currently provides metadata collection and inventories. The dashboard, sample downloader, evidence pipeline, research-card skill, and search service remain to be implemented.

Deliverables:

- Searchable coverage of all 24 investigations in the saved snapshot.
- The complete saved remote-file catalog with pagination.
- Reviewed research cards and supporting evidence.
- Comparisons between two investigations.
- Documented findings and safety implications for BASS-II, Saffire-I, SAME-R, and FLEX.
- Updated documentation and a reproducible local demonstration.

## Coding Ownership

| Collaborator | Implementation ownership | Required code deliverables |
| --- | --- | --- |
| `alan-pv` | Data ingestion and research-card preparation | Sample downloader, PDF extractor, evidence-packet builder, card validator, research-card skill |
| `lm-vicente-j` | Storage, search, and backend | SQLite importer, FTS5 ranking, query handling, HTTP endpoints, integration commands |
| `EmmanuelRamiro23` | Dashboard and application workflows | Search interface, filters, study details, comparison view, evidence viewer, file browser, JSON export |

Each collaborator implements and tests their subsystem. `lm-vicente-j` coordinates integration. Scientific review and presentation work are shared after the first integrated build.

Agree on the JSON and HTTP contracts in hours 0–2. Use the same two-investigation fixture to develop independently.

## Shared Contracts

- Research card: accession, source version, title, cited summary, safety categories, comparison attributes, claims, limitations, and modeling resources.
- Claim: text, evidence IDs, and type—objective, hypothesis, reported observation, or potential application.
- Evidence: stable ID, investigation, source URL, file/version reference, exact excerpt, and metadata-field or PDF-page locator.
- File record: investigation, remote ID, filename, category, extension, version, bytes, and access status.
- Preserve scientific units and source references. Unknown attributes remain unknown.

Every generated summary and claim must reference supplied evidence. Metadata describing a hypothesis or expected impact must not be presented as a measured result.

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

### `lm-vicente-j`: Catalog and Backend

- Implement separate SQLite tables for investigations, cards, evidence, and remote files.
- Import validated records using stable IDs, source versions, and hashes. Repeated imports must not create duplicates.
- Build and validate a replacement database before switching from the last valid version.
- Implement weighted FTS5/BM25 search, prioritizing titles and acronyms. Return matching evidence alongside results.
- Add reviewed synonym mappings for suppression/extinguishment and detection/smoke sensing.
- Keep scientific search separate from filename search. Implement file pagination and category/extension filters.
- Interpret ordinary input as search terms rather than raw FTS syntax. Use parameterized queries and return an explicit no-match state when appropriate.
- Provide repeatable commands to build the catalog and start the application. Lock dependencies after the first working installation.

| Interface | Behavior |
| --- | --- |
| `GET /api/studies` | Search/filter studies; return ranked cards and matching evidence |
| `GET /api/studies/<accession>` | Return a complete card and comparison attributes |
| `GET /api/studies/<accession>/files` | Return paginated remote-file metadata |
| `GET /api/evidence/<id>` | Return an excerpt, source locator, and source URL |
| `GET /api/health` | Return readiness, snapshot date, and indexed counts |

### `EmmanuelRamiro23`: Dashboard

- Implement search, prevention/detection/suppression filters, ranked cards, and study-detail views.
- Show prepared summaries and the evidence explaining each match. Relevance scores must not be presented as fire-risk scores.
- Implement side-by-side comparison of two investigations. Display objectives, findings, fuels, conditions, measurements, limitations, and modeling resources when supported.
- Implement an expandable evidence viewer with source links and page/field references.
- Implement the paginated remote-file browser and research-card JSON export.
- Display loading, empty, missing-evidence, and backend-error states.
- Show the snapshot date and distinguish cataloged files from documents whose contents were processed.
- Label AI summaries as prepared content. Do not present the interface as a live generative chatbot.
- Implement using HTML, CSS, and vanilla JavaScript served by Flask; avoid a separate frontend build system.

## Schedule and Integration

| Hours | `alan-pv` | `lm-vicente-j` | `EmmanuelRamiro23` | Checkpoint |
| --- | --- | --- | --- | --- |
| 0–2 | Define evidence/card fixture | Define database and API contracts | Define screen interactions | Shared contracts frozen |
| 2–12 | Code downloader, extraction, and packet builder | Code importer and search endpoints | Code interface against fixture | Search-to-detail workflow runs |
| 12–24 | Code validator; generate reviewed cards | Complete evidence and file endpoints | Integrate comparisons, evidence, and file browser | Complete workflow with real data |
| 24–36 | Test extraction and audit findings | Test ranking, imports, and failures | Test integrated workflows and fix interface issues | Feature freeze |
| 36–44 | Fix pipeline defects; review citations | Benchmark and package startup | Polish demonstration and export workflow | Release candidate |
| 44–48 | Final evidence review | Resolve release blockers | Complete demonstration and submission | Submit with contingency time |

Stop document collection at hour 12. Continue with available evidence and explicitly identify unmet evidence requirements. Metadata coverage must still include all 24 investigations.

## Acceptance and Testing

- All 24 investigations and the saved remote-file catalog are browsable.
- Every generated summary and claim references valid evidence with a source locator.
- Each core investigation has one verified finding, its conditions, and a supported safety implication.
- At least ten of twelve reviewed search questions return a relevant investigation in the top three. Establish expected matches before evaluating ranking.
- Three unsupported questions return no supported match rather than an invented explanation.
- Comparisons preserve unknown values, units, and differences in experimental conditions.
- Repeated imports produce no duplicates; changed records update correctly.
- Download failures, unreadable PDFs, invalid cards, unknown IDs, and backend errors produce clear states.
- Startup, search, comparison, and evidence viewing work without network access after preparation. Opening external source links requires network access.
- Search targets a 95th-percentile response below one second across 30 representative queries after startup.
- The metadata collector never edits the README.
- Each collaborator supplies tests for their subsystem and records test commands and results in the handoff.

Run tests locally under the existing `test_*` ignore rule. Commit reproducible input fixtures where needed; do not change the ignore rule as part of this MVP.

## Growth and Boundaries

Keep large experimental files with NASA. Scale the catalog and extracted passage index independently of the size of remote archives and videos. Retain stable identifiers, versions, and hashes to support incremental refreshes. Process documents in batches and use structured queries for numerical tables.

Defaults: English interface, local single-user demonstration, and existing assistant access for preparation-time skill execution. Preparation-time AI execution is separate from the offline application; retain generated cards and evidence for independent operation.

Exclude fire simulation, predictive risk scores, embeddings, runtime answer generation, video analysis, OCR, accounts, and public hosting from this release.
