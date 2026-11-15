# Frontend integration

The interface from Emmanuel's `feature-frontend-ui` delivery runs at `/` on the existing Flask server. Only its HTML, JavaScript and CSS were imported; the current backend, schemas and prepared data remain authoritative. The dark theme and existing views are preserved.

## Start locally

Run from the repository root after preparing the PSI sources:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.venv\Scripts\python.exe -m scripts.build_backend
.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000/`. The build uses saved inputs without downloading them. It preserves review states and reports 24 investigations, 261 evidence items, 60,866 catalog entries and 2,009 source rows in the current snapshot. After PR #45, 506 rows meet the backend's verified-run criteria. These counts describe prepared records, not a new scientific review.

## Available workflows

- Search the scientific index, filter by safety category and page through all investigations. Cards show relevance rank, matching excerpts and their actual review state. The header reports the source snapshot date and active counts.
- Open study details to inspect the summary, source version, comparison attributes, typed claims and limitations. Evidence buttons resolve the corresponding citation IDs through the API, including IDs containing `#`.
- Inspect exact evidence text with its metadata field, PDF page or table-row locator and source link. Missing evidence produces an explicit error. The evidence contract has no author field; the viewer directs readers to the original source instead of inventing attribution.
- Browse files for any investigation. Filename, exact category and extension filters combine with pagination. Version, size, access state, source key and download-hash availability remain distinct from content processing. Source links open the investigation in PSI; the API does not supply direct download URLs.
- Page through source rows and their oxygen/pressure values, extraction methods, review state and per-outcome gravity. Normal-gravity results retain the label `1 g ground test`. Intervals stay intervals; missing values stay unknown. The chart plots known point values from the visible page and the three crew-atmosphere references.

API failures stay visible. The application does not silently replace missing data with mock records. Existing mock assets remain available for historical reference but are not loaded by this interface.

## Offline chart

Chart.js was already used by the supplied frontend. Version 4.6.1 is now stored at `static/vendor/chart.umd.min.js` with its MIT license, so opening the application needs no CDN request. SHA-256: `87364cc2b2a76a6684929e7d6b80b18a897794db38400caff1fcf1791c6925d2`.

Source: `https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js`.

## Verification

```powershell
node --check static/app.js
node --test tests/frontend/test_app.cjs
.venv\Scripts\python.exe -m unittest discover -s tests/backend -v
```

The 12 frontend regressions cover server search, pagination, encoded evidence IDs, unavailable-data states, per-outcome gravity, unknowns, intervals, valid zero values, safe text rendering, file filters and local chart assets. All 45 backend tests pass. Three stale test expectations were updated for PR #45: pending review is now explicit in temporary fixtures, modified fixture cards lose their approval, and the current run fixture contains eight verified records. Production review data was not changed.

The current [30-query benchmark](../data/benchmarks/frontend-integration-2026-11-15.json) passes with p95 **387.16 ms** and maximum **387.71 ms**. All eight API smoke routes return 200. Startup takes **33.62 s** and is excluded from request timing. Reproduce it with `.venv\Scripts\python.exe -m scripts.benchmark_backend --output res/frontend-integration-benchmark.json`.

With the Flask server running and Node 22 or later, run the real-data browser check:

```powershell
node tests/frontend/smoke_browser.cjs
```

It launches headless Edge with a separate temporary profile. Set `BROWSER_PATH` to another Chromium executable or `FRONTEND_URL` to another local server if needed. The check requires the full prepared snapshot. It verifies study pagination, search, details, exact evidence, file selection, pagination, all three file filters, empty states, simulated HTTP 503 recovery, mobile overflow, and local chart loading. It rejects JavaScript exceptions and external page requests. The screenshot is saved to ignored `res/frontend-smoke.png`; temporary browser profiles are separate from the user's profile.

## Remaining work

The supplied delivery did not include two-investigation comparison (#26), card JSON export (#28), synchronized condition filters and coverage mapping (#29), or sortable run details and gap states (#30). The chart represents the visible page, not the full condition space. Full frontend demonstration acceptance (#31) and shared contract sign-off (#6) remain open. Evidence author attribution in #25 needs source data beyond the current API record. No interface code approves scientific content or infers safety from an empty query.
