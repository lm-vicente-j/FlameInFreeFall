# Local backend

The Flask application reads prepared PSI cards, evidence, the saved file catalog and normalized run tables. It serves eight JSON endpoints and any frontend assets already present in `static/`. The repository currently has mock assets but no `static/index.html`; `/` therefore returns an explicit `frontend_unavailable` response.

## Install

Run these commands from the repository root with Python 3.11 or later:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.txt
```

The root `requirements.txt` pins direct and transitive runtime dependencies with hashes. Installation needs an available package index or a populated local package cache. The build and benchmark commands below use saved files and make no download requests.

## Build saved data

Prepared cards belong in `data/cards/`, evidence packets in `data/evidence/`, and run tables in `data/runs/`. Each investigation also needs its saved metadata, full remote file inventory and provenance under `res/PSI-<number>/`. The build validates those inputs before publishing artifacts.

```powershell
.venv\Scripts\python -m scripts.build_backend
```

The command writes `res/catalog.sqlite` and `res/runs.ttl`, then prints their paths, counts and health as JSON. It does not regenerate cards, extract documents, fetch remote files or approve pending records. The catalog uses an atomic replacement and retains existing investigations absent from a subset import. Run the command again after preparing new source data. The application loads its run graph from validated JSON tables once at startup; `runs.ttl` is an export of that graph.

Use `--data-dir`, `--res-dir`, `--catalog-path` or `--graph-path` to select other locations. `--approved-only` rejects cards whose scientific review is still pending. Development builds accept pending cards while preserving their status. Input failures cause a nonzero exit and keep the previous catalog generation.

## Start

```powershell
.venv\Scripts\python app.py
```

The local server listens on `http://127.0.0.1:5000`. `create_app(config)` accepts `DATA_DIR`, `RES_DIR`, `CATALOG_PATH` and an optional injected `RUN_GRAPH`. Its default catalog path is `res/catalog.sqlite`. The app never builds a missing database on startup.

| GET route | Result |
| --- | --- |
| `/api/studies` | Literal scientific search and optional cited safety category |
| `/api/studies/{accession}` | Unmodified study card and evidence availability |
| `/api/studies/{accession}/files` | Saved remote file inventory with filename, category and extension filters |
| `/api/evidence/{id}` | Exact evidence record; encode `#` as `%23` in the path |
| `/api/runs` | Unmodified source rows with typed condition and outcome filters |
| `/api/runs/{id}` | One source row and its table provenance in metadata |
| `/api/coverage` | Saved PSI snapshot counts, strict compatibility groups and review limits |
| `/api/health` | Loaded sources, snapshot date and actual record counts |

Study, file and run lists accept `limit` from 1 to 100 (default 20) and nonnegative `offset` (default 0). Empty valid searches return 200 with an empty list. Success responses contain `data` and `meta`; source records remain unchanged. See [the HTTP contract](contracts/API.md) and [active OpenAPI](contracts/openapi-current.json) for parameter names and schemas.

Unknown or repeated parameters, malformed identifiers and invalid numeric bounds return 400 before dataset availability is checked. A missing resource in an available dataset returns 404; required unavailable data returns 503. Unexpected failures return 500 without exception details. Errors contain `error.code`, `error.message` and `error.details` with `state`, `resource`, `parameters` and `health`.

Health is `ready` when both services are loaded, `degraded` when one is loaded and `unavailable` when neither is loaded. Ready and degraded health use HTTP 200; unavailable health uses 503. Missing counts are null; an available empty dataset has count zero. Catalog health follows atomic catalog replacements. Restart the application after changing prepared run tables.

Readiness does not approve scientific findings. Pending or incomplete reviews remain provisional and cannot contribute verified experiments. Sweeps match numeric filters by inclusive range overlap. Quantitative comparisons require equal known fuel class, material, geometry, flow direction and hardware. Unknown conditions remain unknown; empty results do not establish PSI coverage gaps while review or conditions are incomplete. Outcome gravity stays in each source record; there is no gravity filter. Coverage applies only to the saved PSI snapshot.

## Measure request latency

```powershell
.venv\Scripts\python -m scripts.benchmark_backend --output res/backend-benchmark.json
```

The benchmark starts the real application, requires both services to be ready, warms up study and run requests, and checks all eight routes with identifiers from the active snapshot. This smoke check requires at least one study, evidence record and run. It then measures 30 requests: 15 literal study searches and 15 run queries. Queries include common scientific terms, categorical filters, numeric ranges, combined conditions and an empty search. It uses Flask's test client with the actual prepared services and includes request handling and JSON serialization. Startup, warmup and smoke requests are excluded; network and browser rendering are outside this measurement.

The JSON report records each query, status, matching total and elapsed time, plus smoke results, active counts, platform, startup duration, maximum latency and p95. P95 uses the nearest-rank method. The command succeeds only when all eight smoke requests have successful envelopes, every measured query returns 200 and p95 is below 1,000 ms. `--repeat 5` measures 150 requests using the same query set. Report the measured output for the machine and snapshot used; the script does not assume that the target passes.

The measured run at 2026-11-15 20:39 UTC used Python 3.14.7 on Windows 10 and the 2026-11-14 snapshot: 24 investigations and 2,009 source rows, with zero verified experiments. All eight smoke requests and all 30 timed requests returned 200. P95 was **775.26 ms**, maximum latency was **859.21 ms**, and startup took **52.65 s** outside the measured requests. This run passed the latency target. Its local report is `res/http-backend-benchmark.json`, generated with `--catalog-path res/http-build-check.sqlite --output res/http-backend-benchmark.json`. These measurements describe that machine and snapshot; scientific review remains pending.

## Verify

```powershell
.venv\Scripts\python -m unittest discover -s tests/backend -v
.venv\Scripts\python docs/contracts/validate.py
```

Backend tests cover catalog rebuild safety, search, graph semantics, HTTP validation and actual responses against the active OpenAPI document. Their catalog fixtures are tracked under `data/fixtures/backend/catalog/` and run fixtures under `data/fixtures/runs/`; they do not require ignored `res/` inputs. The separate historical validator checks pinned S0 schemas and fixtures. Passing these checks does not replace scientific review or frontend acceptance.

The measured request report is also committed as [backend-2026-11-15.json](../data/benchmarks/backend-2026-11-15.json). [search-2026-11-15.json](../data/benchmarks/search-2026-11-15.json) records all fixed ranking expectations and actual results, including the failed expectation. Keep these measurements distinct from scientific evidence.
