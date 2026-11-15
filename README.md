# Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data

A proposed dashboard for exploring NASA's Physical Sciences Informatics (PSI) combustion research and its relevance to spacecraft fire safety. Research cards summarize and compare investigations. A condition explorer shows which experimental runs cover a scenario, their recorded outcomes, and gaps in the saved PSI tables.

See [APPROACH.md](docs/APPROACH.md) for the proposal and data findings, and [PLAN.md](PLAN.md) for implementation details. The proposal remains under review. The repository provides metadata collection, inventories, and an experimental-table downloader. The dashboard and analysis pipelines remain to be implemented.


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

A skill generates research-card JSON from evidence packets during preparation. Review and validate the cards before import. Convert experimental tables to shared column names and units, reviewing text mappings and extracted observations. Preserve each record's source file, row, and original text. The application displays prepared content without generating answers at runtime.

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

Select up to 20 readable PDFs across BASS-II, Saffire-I, SAME-R, and FLEX, targeting three per investigation and limiting downloads to 250 MB. This is a planned document sample, not an existing download. The metadata collector does not download these documents.

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

The current plan starts normalization with FLEX and Saffire-II, followed by BASS and BASS-II. APPROACH.md leaves the order, flow-sweep display, comparisons across hardware, gravity controls, report-extraction scope, and coverage in later NASA work open for review.


## Implementation Team

| GitHub user | Code ownership |
| --- | --- |
| `alan-pv` | Sample downloader, PDF extraction, evidence packets, research-card skill, card validation, and run normalization |
| `lm-vicente-j` | SQLite import, keyword ranking, RDF run graph, SPARQL queries, backend endpoints, and integration commands |
| `EmmanuelRamiro23` | Search interface, comparisons, evidence viewer, file browser, condition explorer, runs table, and JSON export |

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
