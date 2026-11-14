# Proposed Approach: Explore by Experimental Condition

Status: proposal under review. It adds a run-level layer to [PLAN.md](../PLAN.md) and does not replace it until the team agrees.

## The Argument

NASA's PSI repository holds more than 13 TB of microgravity combustion data. The current plan builds a search tool that summarizes each investigation separately. But a summary stops at the investigation. A user who needs to know which tests covered a specific condition, and what happened, still has to open reports and files across several investigations to find the runs that matter. NASA's own BASS-II objective is to "bridge the gap between the normal gravity NASA-STD-6001 Test #1 method, ground-based microgravity tests, and actual material flammability in microgravity", and to feed the computational models used to design fire detection and suppression systems. Therefore, we propose a condition explorer underneath the research cards. The user describes a scenario (oxygen, pressure, airflow, and material), and the dashboard shows which real test runs cover it, what outcome each recorded, which file holds its data, and where PSI has no run at all.

The cards still summarize, rank, and interpret investigations, which the challenge asks for. The condition explorer serves the second challenge goal, extracting data that supports predictive modeling.

## How It Works

1. **Normalize** each investigation's per-run table into one schema with shared column names and units.
2. **Filter** by the categorical constraints that make runs comparable: fuel class (solid, droplet, or gas), material, geometry, and flow direction.
3. **Map coverage**. Plot the filtered runs on oxygen against pressure, with the three atmospheres NASA considers for crewed missions marked: 14.7 psia with 21% O2, 10.2 psia with 26.5%, and 8.2 psia with 34%. List the runs in a sortable table next to the plot.
4. **Flag gaps**. When no run sits near the scenario, report that PSI has no evidence for it. This means "not in PSI", not "never studied".
5. **Link** each run to its source files and to cited passages from reports. Show the authors' conclusions only, with no conclusions of our own.

We dropped an earlier idea of ranking runs by a normalized distance to the scenario. After the categorical filter, solids, droplets, and gas flames form three groups that share no runs. Within solids, only oxygen and flow vary, and flow is not yet in physical units. A single distance score would imply a precision the data does not have.

## What the Data Contains

On 2026-11-14 we downloaded every `Experimental table` CSV in the 24 investigations, plus the BASS test-matrix spreadsheets, using [scripts/fetch_experimental_tables.py](../scripts/fetch_experimental_tables.py). The 22 CSVs total about 230 KB and about 2,010 non-empty rows. They do not share a schema.

| PSI | Investigation | Rows | Conditions recorded | Outcomes recorded |
| --- | --- | ---: | --- | --- |
| 25 | BASS-II (solids) | 129 runs, 6 PIs | Material, O2 13.6–22.2% (initial and final), CO2, CO, flow as fan and air **display readings** | None in its own column. Extinction and blowoff appear as free text in the flow columns |
| 26 | BASS (solids) | 122 runs | CSV: material only. As-run XLSX adds O2 fraction, pressure (0.97–0.98 atm in the rows inspected), CO2, and fan display | Free-text "Test Observations and Anomalies" per run in the XLSX, such as burn time, no ignition, and extinction |
| 98 | Saffire-I (large solids) | 2 runs | SIBAL fabric, 20 cm/s, ~21.5% O2, flow direction | Burn time |
| 99 | Saffire-II (solids) | 9 samples | Material, thickness, 20 cm/s, ~21.5–22.1% O2 | **Microgravity burn length next to 1 g burn length and spread rate**, mostly as text ("Complete", "~ 0") |
| 100 | Saffire-III | 2 runs | SIBAL, 30 cm/s, flow direction | None |
| 69 | FLEX (droplets) | 274 runs | Methanol and heptane, pressure (103 runs below 600 mmHg), O2 0.12–0.34, N2, CO2 (123 runs), He (50 runs) | Extinction diameter (197 runs), burning rate, burn time, end type |
| 68 | FLEX-2 | 8 rows | Ranges per fuel, not per run | None |
| 101 | SAME-R (smoke) | 109 runs | Material, inlet velocity, aging times | No particle-size results in the table |
| 102 | SAME (smoke) | 4 runs | Material, airflow, aging duration | Weight loss rate |
| 39 | CFI (cool flames) | 87 runs | Pressure 0.5–5 atm, O2 0.17 or 0.21, diluents, fuel | None |
| 159 | CFI-G (cool flames, gas) | 333 runs | Pressure 0.5–3.3 bar, O2 0.12–0.85, fuel | Hot ignition, burn time, and extinction type |
| 10 | Flame Design | 327 runs | O2, pressure, flow rates, computed adiabatic temperature | None |
| 107 | SPICE | 469 rows, 435 unique | Fuel, nozzle, fuel rate, air rate | None. The table has no smoke-point column |
| 20–23, 106 | ACME BRE, CLD, E-FIELD, s-Flame, SLICE | 12–32 rows each | Session-level summaries | Number of flames ignited |
| 47, 142 | DAFT, CFE counterflow | 2, 8 rows | Session or figure references | Pointers to publications |

The modeling-only investigations (PSI-60, 62, 115, 117) publish no experimental table.

Data-quality notes:

- The CFI-G inverse-flame CSV has 861 empty rows out of 1,015. The 333 runs above exclude them.
- Saffire-I, Saffire-II, and SAME mix runs with note rows. SAME rows 5–8 only say "same conditions as 1-4".
- FLEX test 114 lists a pressure of 0 mmHg, which is not a valid reading.
- BASS-II uses 51 different strings for about ten materials, for example `1/4" black rod` and `1/4 black rod`.
- ACME BRE lists oxygen as `3400%` and `2100%` in two rows.

## Early Findings

- **No solid-fuel run is above 22.2% O2 or below about 0.97 atm.** BASS-II spans 13.6–22.2% O2, and 88 of its 129 runs start below about 20.5% because it studies extinction limits. Saffire stays near 22%. Nothing in the solid-fuel tables reaches the enriched, reduced-pressure atmospheres proposed for exploration habitats (8.2 psia with 34% O2).
- **Two investigations partly reach those atmospheres with other fuels.** ACME BRE names all three exploration atmospheres in its PSI objectives and aims at "fuel conditions that can be related to a diverse range of condensed fuels", but its table is a session summary. FLEX has 17 droplet runs below 600 mmHg with at least 30% O2.
- **A BASS-II run is a sweep, not a point.** Only 19 of 129 rows give a single fan reading. The others record flow being stepped down until the flame goes out, as in `5 down to ext` or `10 blowoff`. The extinction limit is the result, and it sits in free text.
- **BASS and BASS-II record flow as instrument readings, not velocities.** Converting them requires the `Fan calibration data.xlsx` reference file, which is organized by test date and by number of flow restrictors.
- **Saffire-II directly compares 1 g and microgravity burning** for the same materials. Thin silicone burned completely at 1 g and did not burn in microgravity. This is the kind of evidence NASA says it needs.
- **FLEX holds suppression evidence.** Its runs with CO2 and helium record extinction, which supports the challenge goal on suppression equipment.
- **Outcomes are often missing from the tables.** BASS-II and SAME-R outcomes live in videos and reports. The 127 PDFs in BASS-II are mostly per-test `ProofSheet` files, and we have not checked whether they contain extractable text. Report text extraction (keyword search or RAG) complements the condition tables rather than replacing them.
- **Runs link to files.** BASS-II filenames include sample and test numbers, for example `SAMPLE_205_TEST_O3a`, which match the table columns.

## Open Questions

- Which investigations to normalize first. FLEX, BASS (as-run XLSX), and Saffire-II have the most usable outcomes. BASS-II has the most conditions but no outcome column.
- How to show a flow sweep: as a range per run, or as one point per step.
- Whether later NASA work (Saffire-IV to VI, SoFIE) already covers the enriched-oxygen gap for solids and is simply absent from PSI. We have not verified this.
- How to compare runs with different hardware, fuels, and flow definitions without misleading users.
- Whether gravity should be a variable when almost every run is at microgravity and no partial-gravity data exists.
- How much report extraction is needed to fill missing outcomes within the hackathon.
