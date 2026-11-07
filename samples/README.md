# Synthetic data

Everything here is generated from [`HappyHealth_CMS_Measures_Synthetic_Data.xlsx`](HappyHealth_CMS_Measures_Synthetic_Data.xlsx) (seed 42). Names, record numbers and provider IDs are fake. 43 source records (28 Epic, 15 MEDITECH) for 41 people at link version 8, 93 visits, 44 ED visits, 12 sepsis episodes at 8 of the 17 hospitals (6 Epic, 2 MEDITECH), reporting period 1 July – 30 September 2026.

| Folder | Contents | Produced by |
|---|---|---|
| `bronze/epic_fhir/` | `Patient`, `Encounter`, `Condition` as FHIR R4 NDJSON, the shape of an Epic bulk export. ED tracking times sit in a Happy Health extension on Encounter (assumed mapping, to confirm). Instants carry a UTC offset. | `tools/make_bronze.py` |
| `bronze/meditech_hl7v2/` | One nightly file per day of `ADT^A03` messages: PID, PV1 (PV1-19 visit number, PV1-36 disposition, PV1-44/45 times), DG1 (DG1-15 = 1 for the principal diagnosis) and the assumed `ZET` segment for ED tracking events. Local times, no offset. | `tools/make_bronze.py` |
| `silver/clinical/` | FHIR-shaped conformed tables in hospital local time | `tools/export_samples.py` |
| `silver/identity/` | `dimPatientSource`, `dimPerson`, `bridgePatientLinkHistory` (versions 1–8), `linkVersion` control table, `matchCandidatePairs`, `reviewQueue` | export + hand-written samples |
| `gold/` | Quality star schema, `dimMeasure`, `dimCalculationRun`, `factMeasureResult` and `factMeasureSummary` for run R-2026Q3-01 | `tools/export_samples.py` |
| `reference/expected_results.json` | The workbook's summary results, used by the tests | `tools/export_samples.py` |

The identity story the samples tell:
* **MEDI-88015 = EPIC-10015**: identical details, linked by the exact rule in version 1.
* **MEDI-88005 → P-0005** in version 7: a common name and missing birth date kept it separate at first; after retraining (MDM-2) it scored 0.81, a steward confirmed it, and P-0041 was retired with a forwarding pointer. This match is what makes the Riverside readmission count.
* **MEDI-88012 split from P-0012** in version 8: auto-linked at 0.97 under MDM-1, reported by a care manager, split by a steward into new person P-0042. Run R-2026Q3-02 shows readmission 11.9% instead of 14.3%.
