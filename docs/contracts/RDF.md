# RDF mapping contract

Map supported normalized values without asserting that a source row is a verified individual experiment. [expected/runs.ttl](../../data/fixtures/s0/expected/runs.ttl) is a Turtle fixture written in its N-Triples subset: absolute IRIs, one triple per line and escaped literals. It contains source-backed values from the two run-table fixtures; no loader is implemented.

Use [SOSA/SSN](https://www.w3.org/TR/vocab-ssn/) for observations and context, [QUDT](https://www.qudt.org/doc/2025/03/DOC_SCHEMA-QUDT.html) for values and units, and [PROV-O](https://www.w3.org/TR/prov-o/) for source/extraction provenance. Dublin Core supplies descriptive identifiers and membership; RDFS/SKOS supplies labels and material concepts. The project namespace adds only fuel classes, material concepts and outcome types. Its terms do not establish a reviewed material hierarchy.

## Namespaces and identity

| Prefix | Namespace |
| --- | --- |
| `sosa` | `http://www.w3.org/ns/sosa/` |
| `ssn` | `http://www.w3.org/ns/ssn/` |
| `qudt` | `http://qudt.org/schema/qudt/` |
| `unit` | `http://qudt.org/vocab/unit/` |
| `prov` | `http://www.w3.org/ns/prov#` |
| `dct` | `http://purl.org/dc/terms/` |
| `project` | `https://flameinfreefall.local/vocab/` |

Resource base: `https://flameinfreefall.local/resource/`. These are identifiers; resolving them over HTTP is not required. Encode each ID segment as UTF-8 percent encoding, keeping only URI unreserved characters (Python `quote(value, safe='')`). Do not hash or rename upstream row IDs.

| Resource | Suffix after the resource base |
| --- | --- |
| Investigation | `investigation/{accession}` |
| Exact table bytes | `source/sha256/{source.sha256}` |
| Source row | `row/{encoded record.id}` |
| Condition | `row/{encoded record.id}/condition/{field}` |
| Reported outcome | `row/{encoded record.id}/outcome/{zero-based outcome index}` |
| Outcome result | Outcome suffix followed by `/result` |
| Extraction activity | `activity/{method}` |

Outcomes retain upstream array order. Changing that order regenerates outcome resources; the row ID stays stable. A graph build represents one current prepared snapshot. Keep source hashes and versions to distinguish a changed preparation from an unchanged identity.

## Field mapping

| Input | RDF representation |
| --- | --- |
| Table `source` | `prov:Entity`; `dct:title` is the exact filename; `dct:identifier` is the downloaded SHA-256. `prov:value` holds the exact catalog adapter JSON, including accession, file ID, key and file version. |
| Record `id` | Row `prov:Entity` with exact `dct:identifier`; `prov:wasDerivedFrom` the table entity; `dct:isPartOf` the investigation resource. Do not type every row as `sosa:Observation`. |
| Record `row`, `original`, `kind`, `review_status` | One JSON string in row `prov:value`, with sorted keys. This preserves row index, every original cell and pending classification/review. |
| Known numeric condition | Row `ssn:hasProperty` a condition resource, typed `ssn:Property` and `qudt:QuantityValue`; exact field name in `dct:identifier`. |
| Known `material` | Row `dct:subject` a `project:material/{encoded exact value}` SKOS concept with the exact source label. A row-specific condition provenance entity records the category extraction details. No synonym or hierarchy is inferred. |
| Reviewed `fuel_class` | Row `dct:subject` `project:fuel/solid`, `project:fuel/droplet` or `project:fuel/gas`. These fixture values are unknown, so no fuel-class triple is present. |
| Known outcome | One `sosa:Observation` per recorded outcome, `sosa:hasFeatureOfInterest` the row entity, `sosa:observedProperty` `project:outcome/{type}` (a `sosa:ObservableProperty`), `sosa:hasResult` the result resource. This describes a reported outcome, not an experiment census. |
| Outcome `gravity` | Observation `dct:description` literal `gravity=microgravity` or `gravity=normal`. Keep each paired result separate. No run-level gravity is inferred. This descriptive encoding does not settle #35 filtering. |
| Quantity point (`min == max`) | Result/condition `qudt:QuantityValue`, `qudt:numericValue` as `xsd:decimal`, and `qudt:unit`. |
| Quantity interval (`min != max`) | Parent `qudt:QuantityValue` with unit, and `dct:hasPart` two QuantityValues at `/min` and `/max`, each with matching `dct:identifier`, unit and numeric value. No parent point value or midpoint. This retains bounds; sweep/filter interpretation remains provisional. |
| Qualifier `approximate` | Quantity `dct:description` literal `qualifier=approximate`. It does not specify a statistical uncertainty. |
| Known categorical outcome | `sosa:Result` with the exact label in `prov:value`. `Complete`, `Acceleratory`, `Insignificant` and `~ 0` are labels, not numeric measurements. |
| Value provenance | `prov:wasDerivedFrom` the row; `prov:wasGeneratedBy` the method activity; `prov:value` is the complete value JSON with method, columns, quote, note and review status. JSON literals use sorted keys and ASCII escapes. |

Each outcome also carries the description “Source-reported outcome; review pending; individual-experiment classification unresolved.” This label and the JSON provenance keep structural extraction separate from scientific review. No reviewer, observation time, sensor, procedure, calibration or approval is invented. Extraction activities describe preparation methods, not the physical experiment.

## Units and unknowns

| Input unit | QUDT unit |
| --- | --- |
| `percent` | `unit:PERCENT` |
| `kPa` | `unit:KiloPA` |
| `cm/s` | `unit:CentiM-PER-SEC` |
| `s` | `unit:SEC` |
| `mm` | `unit:MilliM` |
| `cm` | `unit:CentiM` |
| `mm/s` | `unit:MilliM-PER-SEC` |

If a category is null, or either numeric bound is null, omit its scientific value resource and triples. Preserve the original cells in row provenance and the complete normalized record in JSON. Never emit zero, NaN, an empty measurement or a generic “unknown” material resource for missing data. A source zero may be retained only when valid and supported; FLEX's 0 mmHg is invalid and has no pressure triple.

The fixture retains known oxygen, pressure, flow, material, burn time, extinction diameter, test-end labels and paired gravity outcomes where supplied. A blank FLEX extinction diameter produces no observation for that array slot. Saffire-II's blank material produces no material assertion.

## Unsupported mappings

- Range/session/duplicate classification and verified experiment totals: the schema only distinguishes `run` and `note`.
- Dedicated initial/final conditions, experimental run-to-file assets and report-evidence links: the schema has no dedicated fields. Table provenance is supported.
- Fuel-class aliases, material synonyms/hierarchies, geometry, flow direction and diluent vocabulary alignment: preserve JSON and original text until reviewed mappings exist. Null fields generate no facts.
- FLEX burning rate: `Burning rate; mm` does not establish the rate unit.
- Saffire-II `?-g Spread Length`: selected cells report mm/s despite the length header. Do not silently reclassify them.
- Flow calibration, flow-sweep time steps, cross-hardware equivalence, gravity filtering, coverage bins and empty-region assertions: blocked by schema gaps and #33–#35.
- Automatic approval of extraction results, safety conclusions or individual experiments. Metadata-only cards support objectives; they do not establish findings.

The saved Saffire-II `?-g` header and shared burn-time gravity interpretation are tentative and await Alan's review. Their pending state is recorded in the fixture manifest, JSON values and RDF provenance.
