---
name: research-card
description: Draft one Flame in Freefall research card from one PSI evidence packet (data/evidence/PSI-<n>.json), then finalize and validate it with the project pipeline. Use only when explicitly asked to draft or regenerate a research card for a given accession in the FlameInFreeFall repository.
---

# Research-card drafting

To use this skill with Claude Code, copy this file to `~/.claude/skills/research-card/SKILL.md`. The copy in `docs/` is the reviewed source of truth.

You turn ONE evidence packet into ONE research-card draft. Your output is read by NASA reviewers: every statement must be traceable to an exact excerpt. A person reviews every card afterwards; you never approve anything.

## Inputs

- Packet: `data/evidence/<ACCESSION>.json` (passages with `id`, `locator`, `text`). These passages are the ONLY allowed source. Do not use outside knowledge, other packets, or the web.
  - `meta:` passages are PSI metadata fields.
  - `pdf:` passages are document pages.
  - `table:` passages are rows of PSI's official experimental tables, rendered as `Header: value | Header: value`. The values in a table row were recorded per test run, so a row can support a `reported_observation`. State the run's conditions from the same row, and never generalize from a few rows to a trend the source does not state.
- Draft contract: `pipeline/schemas/research-card-draft.schema.json`.
- Remote file keys (for modeling resources): `metadata-info/<ACCESSION>.md` table rows starting with `| psi-data/`.

## Output

Write the draft to `res/drafts/<ACCESSION>.json`, then run from the repository root:

```
<python> -m pipeline.cards finalize res/drafts/<ACCESSION>.json
```

`<python>` is the project's Python with `pipeline/requirements.txt` installed. If finalize reports problems, fix the draft and run it again until it writes `data/cards/<ACCESSION>.json`. Never edit `data/cards/` by hand.

## Rules

1. Evidence items are `{"id": "E<n>", "passage_id": ..., "excerpt": ...}`. The excerpt is copied character for character from that passage's `text` (whitespace and ligature differences are tolerated when locating it, and finalize stores the exact text of the passage), is at least 20 characters long, and is as short as possible while still supporting the statement. Never paraphrase inside an excerpt.
2. Every statement (summary, claim, finding conditions, comparison attribute, limitation with basis "source", modeling resource) cites the `E<n>` refs that support it. Every number you write must appear in an excerpt cited by that same statement. If it does not, remove the number. Numbers are checked as quantities, not as digit strings: the sign counts (`-5` is not `5`), an exponent is part of the number (`1e-6`, `10^-6` and `x10-6` are one quantity), a unit written right after a number (kPa, mmHg, %, s, mm, cm/s, ...) must be the unit the excerpt gives that number (table headers such as `Burn time; s` count), and all numbers in one sentence must occur together in one single cited excerpt. So write one group of values per sentence and never mix values from two table rows or two pages in one sentence; a sentence about test #94 must not carry numbers that only appear in the row of test #226.
3. Claim types:
   - `objective`: what the investigation set out to do.
   - `hypothesis`: what it expected or proposed to test.
   - `reported_observation`: a result that was measured or observed. It must cite document text or a metadata field that states a result. Objectives, hypotheses, and research impacts are never evidence of a result.
   - `potential_application`: a safety use the source itself supports.
   Wording must match the type. Write "aims to" and "hypothesizes that" for intent, and "measured" and "observed" only for results.
4. `safety_categories`: prevention, detection, or suppression, each only when an excerpt supports it.
5. `findings`: link a reported observation claim, the conditions under which it was observed (cited), and a potential application claim. For PSI-25, PSI-98, PSI-101, and PSI-69, include at least one finding. If the packet holds no reported result, stop and report that instead of inventing one.
6. `comparison`: fill fuels, geometry, oxygen, pressure, flow, gravity, measurements, and hardware only when the packet documents them. Otherwise use `null`. Unknown stays unknown.
7. `limitations`: state source limitations with `basis: "source"` and citations. When the packet `coverage` is `metadata_only`, add one limitation with `basis: "coverage"` and empty `evidence_ids`, stating that only PSI metadata was examined and no document text was processed.
8. `modeling_resources`: name measurements or remote files that could support future predictive modeling, using exact `psi-data/...` keys from the inventory. Never claim that a model exists or was validated.
9. `generation`: `{"model": "<your exact model id>"}`.
10. Use plain, precise English and no marketing language. Keep source spellings and units as written.

## Finish

Report the accession, the finalize result, the number of claims and findings, and any unmet requirement, for example a core investigation without a documented result.
