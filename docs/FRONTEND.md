# Research interface

The interface at `/` is an offline evidence explorer for academic and research users. It is plain HTML, CSS and JavaScript served by the existing Flask application, with no build step, no runtime dependencies and no requests outside the local server. External links to PSI and DOI landing pages are the only network use, and only when followed.

It replaces the first integrated dashboard (Spanish, `static/app.js`, Chart.js). That version's regressions were ported to the module tests below. The language is English, as PLAN.md specifies.

## Start locally

From the repository root, after preparing the PSI sources:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.venv\Scripts\python.exe -m scripts.build_backend
.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000/`. Startup loads the catalog and run graph and takes about 35 s.

## Workflows

Every view keeps its state in the URL hash, so a search, a comparison, a filtered set of runs or an open run record can be bookmarked or shared.

| View | Route | What a researcher can do |
| --- | --- | --- |
| Investigations | `#/studies?q=&category=` | Full-text search (FTS5/BM25) over cited evidence, filter by safety category, see matching excerpts with highlighted terms and their relevance rank (labelled as not a risk measure), and pick two investigations to compare. |
| Investigation record | `#/study/PSI-69` | Read the cited summary, safety categories, comparison attributes, claims grouped by type (reported observations kept apart from objectives, hypotheses, expected impacts and applications), findings, limitations and modeling resources. Citation markers open the exact excerpt with its locator, and a numbered reference list closes the page. Shows the review state, reviewer and drafting method, the PSI investigators, DOI, licence and publications. Offers **Cite** (plain text and BibTeX, built only from PSI metadata) and **Export card (JSON)** (#28). |
| Evidence viewer | dialog | Exact excerpt, metadata field, PDF page or table row locator, evidence ID, source link, and attribution to the PSI-listed investigators, noting that the cited document's own authorship may differ (#25). |
| Compare | `#/compare/PSI-69/PSI-99` | Two records' cited statements side by side, grouped into overview, aims, results, experimental conditions, methods, limitations and modeling resources. Nothing is normalized or differenced; missing content reads "Not stated in this card". Applies the D3 rule and can be downloaded as CSV (#26). |
| Condition explorer | `#/conditions?fuel_class=solid&o2_min=21` | Filter by fuel class, material, geometry and flow direction, then O₂, pressure (kPa, atm or psia), flow and outcome (#29). Shows coverage counts and status from `/api/coverage`, an SVG oxygen–pressure map of every matching record with the three crew-atmosphere references and the active filter window, condition groups with their D3 compatibility, and the gap message, which applies only to the saved PSI snapshot. Filtered records download as CSV or JSON. |
| Runs table and record | in the explorer, `&run=<id>` | Sortable table with client-side pagination; unknowns sort last. Values extracted by AI and uncalibrated flow display readings are marked. The record dialog shows every condition and outcome with method, review state, source columns, source text and notes, the original row cells verbatim, flags, and confirmed or ambiguous file links. Gravity stays on each outcome, and normal gravity reads "1 g ground test" (#30). |
| Files | `#/files/PSI-69?category=Experimental%20table` | Browse the PSI file inventory by filename, category and extension. Catalogued files are distinguished from verified downloads, and the filtered list exports as CSV. |
| About the data | `#/about` | Preparation method, review states, count basis, comparison and gap rules, exclusions, API endpoints for programmatic access, and citation guidance. |

API failures stay visible as errors; there is no fallback to mock data.

## Structure

| File | Role |
| --- | --- |
| `static/index.html` | Shell: header with snapshot status, navigation, main view, footer. |
| `static/js/core.js` | Shared `FF` namespace: safe DOM builder, API client, quantity formatting, labels, hash routing, CSV and download helpers. |
| `static/js/main.js` | Health status, navigation and routing. |
| `static/js/studies.js` | Investigation search, record page, citations and `FF.evidence`. |
| `static/js/compare.js`, `files.js`, `conditions.js`, `runs.js`, `about.js` | One module per view; `runs.js` provides `FF.runs` to the explorer. |
| `static/css/base.css` | Design tokens (light and dark), typography, tables, forms and print styles. Each view adds a small stylesheet. |

Text is rendered with `textContent` only. External links are restricted to http(s). Evidence and run identifiers are percent-encoded in request paths.

## Backend additions

- `GET /api/studies/{accession}` adds `meta.source`: DOI, PSI URL, licence, investigation dates, investigators (name, roles, affiliation; never contact details) and publications, all copied from saved PSI metadata. It is `null` when that metadata is unavailable. The card in `data` is unchanged. See [API.md](contracts/API.md).
- The run graph parses its three fixed SPARQL queries once at import and evaluates them under a lock. rdflib's parser is not thread-safe: concurrent filtered requests on the threaded Flask server had corrupted it and made every later filtered request return HTTP 500 until restart. `tests/backend/test_graph.py` reproduces the race.

## Verification

```powershell
node --test tests/frontend/test_*.cjs
.venv\Scripts\python.exe -m unittest discover -s tests/backend -v
node tests/frontend/smoke_browser.cjs   # with the server running; Node 22+
```

On Node 24 pass the test files explicitly; a bare directory argument fails. The unit tests load each module in a small fake DOM (`tests/frontend/harness.cjs`). The browser check drives headless Edge through the DevTools protocol against the full prepared snapshot. It rejects JavaScript exceptions and any non-local request, emulates a 390 px phone to check for horizontal overflow on every view, and saves screenshots under ignored `res/smoke/`. Set `BROWSER_PATH` or `FRONTEND_URL` to use another Chromium or server.

## Known limits

- Under concurrent load the Flask development server on Windows occasionally ends a large response early while logging HTTP 200. `FF.api` retries idempotent GETs twice after a connection failure or a truncated body, but never after an HTTP error or an abort. A shared or public deployment should run behind a production WSGI server.
- The PSI metadata gives no dataset publication year, so citations omit the year and give the snapshot access date.
- The condition explorer fetches every matching record (up to 2,009, about 10 MB) to keep the map, counts and table in agreement. This is fast locally. A public deployment should add a compact endpoint or precomputed files.
- PLAN.md's initial finding that no solid-fuel run exceeds 22.2% O₂ does not hold exactly in the current records: 20 BASS (PSI-26) rows record 22.22–22.72% O₂. No solid-fuel record falls below about 0.97 atm. The data was not changed; the finding needs scientific review.
- Scientific review of cards, aliases and extractions is separate from interface acceptance; the interface shows each record's review state and does not approve content.
