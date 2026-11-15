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
