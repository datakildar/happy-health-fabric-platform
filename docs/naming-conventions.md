# Naming conventions

> Part of the [Happy Health Fabric platform](../README.md) documentation.

Agree these before the first table is created; renaming in production breaks reports, shortcuts and lineage.

## Workspaces – `happy-<domain>-<env>`

| Example | Holds |
|---|---|
| `happy-engineering-prod` | Bronze, silver and identity lakehouses, ingestion and matching notebooks, pipelines |
| `happy-quality-prod` | Gold quality lakehouse, measure notebook, quality semantic model |
| `happy-pophealth-prod` | Patient 360 mart (after day 120) |
| `happy-research-prod` | Released de-identified extracts and the restricted crosswalk lakehouse |
| `happy-monitoring-prod` | Monitoring lakehouse and audit model |
| `happy-reports-prod` | Power BI apps for business users |

Lowercase, hyphens, environment last (`dev`, `uat`, `prod`). Item names are identical across environments so deployment rules only swap workspace IDs.

## Lakehouses – `lh_<layer>[_<domain>]`

`lh_bronze`, `lh_silver`, `lh_silver_identity`, `lh_mdm`, `lh_gold_quality`, `lh_gold_pophealth`, `lh_research`, `lh_restricted`, `lh_monitoring`. Snake case with the `lh_` prefix. See [`templates/lakehouse_config.json`](../templates/lakehouse_config.json).

## Tables and columns – camelCase

| Kind | Pattern | Examples |
|---|---|---|
| Gold fact | `fact<Subject>` | `factVisit`, `factEdVisit`, `factSepsisEpisode`, `factMeasureResult`, `factMeasureSummary` |
| Gold dimension | `dim<Subject>` | `dimMeasure`, `dimCalculationRun`, `dimLocation`, `dimPatientSource`, `dimPerson` |
| Bridge | `bridge<Subject>` | `bridgeDiagnosis`, `bridgePatientLinkHistory`, `bridgeCareManagerPanel` |
| Silver | FHIR resource name, camelCase | `patient`, `encounter`, `condition`, `edTrackingEvent`, `sepsisEpisode` |
| Control and logs | noun | `linkVersion`, `reviewQueue`, `notebookRunLog`, `notebookErrorLog`, `quarantine` |
| Columns | camelCase; keys end in `Key` (gold) or `Id` (silver); flags start with `is`/`in`; times end in `DateTime` or `Time` | `sourcePatientKey`, `encounterId`, `isExclusion`, `inNumerator`, `arrivalDateTime` |
| System columns | leading underscore | `_sourceSystem`, `_loadTimestamp`, `_batchId`, `_pipelineRunId`, `_lastUpdated` |

Source patient keys are prefixed with their system: `EPIC-<MRN>`, `MEDI-<MRN>`, `LAB-…`, `RX-…`, `CLM-…`. Person IDs are `P-0000` and never reused.

## Notebooks, pipelines and models

| Item | Pattern | Examples |
|---|---|---|
| Notebook | `<nn>_<verb>_<subject>` | `03_patient_matching_splink`, `05_measure_calculation` |
| Pipeline | `pl_happy_<scope>_<frequency>` | `pl_happy_nightly`, `pl_happy_measures_quarterly` |
| Semantic model | `Happy<Subject>` | `HappyQuality`, `HappyPatient360` |
| Calculation run | `R-<yyyy>Q<q>-<nn>` | `R-2026Q3-01` |
| Matching run | `MR-<yyyymmdd>` | `MR-20260929` |
| MDM settings version | `MDM-<n>` | `MDM-3` |
