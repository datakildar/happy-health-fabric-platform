# Architecture decision records

> Part of the [Happy Health Fabric platform](../README.md) documentation.

Each record states the context, the decision, why, and what it costs. Status values: *Accepted*, *Proposed* (needs a stakeholder decision in week one), *Superseded*.

---

## ADR-001: Microsoft Fabric as the platform
**Status:** Accepted · **Date:** 2026-11

**Context.** 17 hospitals (12 on Epic, 5 acquired on MEDITECH), two record systems, four ancillary sources, four consumer groups, an incremental budget and a 120-day deadline for five CMS measures.

**Decision.** Build on Microsoft Fabric: Pipelines, OneLake shortcuts and mirroring for loading; lakehouses on OneLake (Delta) for storage; Spark notebooks for engineering; Power BI Direct Lake for reporting; Purview, Entra ID and OneLake security for governance.

**Why.** One platform covers loading, storage, engineering, reporting and alerting, which matters on an incremental budget. Healthcare Data Solutions gives tested FHIR pipelines. Power BI is native. Open Delta tables plus open-source tools (Splink, Presidio) keep a later move to storage work rather than a redesign.

**Costs.** Capacity-based pricing needs active monitoring; some features we'd like (OneLake row-level security, workspace monitoring) were still in preview when this was written. Databricks and Snowflake were credible alternatives: Databricks would give stronger engineering and machine-learning depth and native HL7v2 parsing, at the cost of building the FHIR mappings and licensing Power BI separately.

---

## ADR-002: Medallion layers with bronze as the audit trail
**Status:** Accepted

**Decision.** Bronze keeps every source record exactly as received (append-only, 7-year retention to confirm). Silver holds FHIR-shaped, cleaned, coded tables and the identity tables. Gold holds marts shaped per consumer: quality star schema, population health 360, operational marts, de-identified research area.

**Why.** Any number can be traced back to the message it came from, and history can be reprocessed when a rule changes. Silver is organized by subject and reusable; gold is organized by use, so numbers agree across consumers.

**Costs.** Roughly three copies of clinical data; mitigated by compression and by reading identity through shortcuts instead of copying.

---

## ADR-003: One FHIR-shaped model for every source
**Status:** Accepted

**Decision.** Every source is converted to FHIR R4 at ingestion. Epic exports FHIR; MEDITECH HL7v2 is converted with Microsoft's FHIR Converter; ancillary systems are mapped to the same silver tables.

**Why.** One storage format and one set of silver tables means the measures are written once, and the next acquisition becomes configuration work.

**Costs.** Conversion adds a step for HL7v2 sources (see ADR-004).

---

## ADR-004: MEDITECH HL7v2 through the FHIR Converter, owned by Happy Health
**Status:** Accepted, with known gaps

**Context.** Healthcare Data Solutions ingests FHIR NDJSON only. The converter's templates are samples that Microsoft doesn't support for production; they target HL7 v2.8, have no medication administration (RAS) template, don't read custom Z segments, and have open bugs that affect encounter IDs (PV1-19 without an assigning authority) and lab results with several OBX rows. HL7v2 times have no UTC offset.

**Decision.** Fork and pin the templates under version control; write templates for RAS and the ED tracking events; fix the two bugs in the fork; set the hospital time zone explicitly; validate every converted resource and reconcile message counts nightly (`notebooks/01_meditech_hl7v2_to_fhir`). The `ZET` segment is read by the reference parser (`src/happy_platform/hl7v2.py`).

**Alternatives kept open.** Parse the few needed segments straight into silver; another open-source converter; MEDITECH's FHIR interface if MEDITECH can license it (removes the conversion entirely).

---

## ADR-005: Probabilistic matching with Splink; thresholds in MDM settings
**Status:** Accepted

**Decision.** Splink (Fellegi-Sunter, weights trained on Happy Health's data) runs in a Fabric Spark notebook. Two thresholds from the MDM source split pairs into auto-link, steward review and keep separate. Precision and recall are measured on a hand-labelled Epic–MEDITECH sample. Splink is pinned to 4.x.

**Why.** Explainable field by field, open source, scales on Spark, and a commercial matching product can replace it later behind the same link history.

**Costs.** A steward review queue must be staffed. Social Security numbers, if any source has them, are one weighted field, never a deciding key.

---

## ADR-006: Versioned patient links; facts store the source record
**Status:** Accepted

**Decision.** Facts keep `sourcePatientKey`. `bridgePatientLinkHistory` says which person each record belongs to, by link version (`versionFrom`/`versionTo`, with valid-from and recorded-at dates). A version is published only when identity changed; old rows are closed, never deleted; a control row flipped to *published* last is the commit point.

**Why.** A merge or split never rewrites facts, and any result can be rebuilt as of the day it was submitted.

**Costs.** Queries resolve the person through the bridge; each run materializes the links it used so joins stay simple.

---

## ADR-007: Frozen calculation runs pin their versions
**Status:** Accepted

**Decision.** A run records the link version, MDM settings version, code version and period in `dimCalculationRun` before calculating. Submitted runs are frozen; a recalculation is a new run beside the old one, with a difference report.

**Why.** Filed numbers never change silently; auditors see exactly which identity state and settings produced each number.

---

## ADR-008: A generalized measure result model
**Status:** Accepted

**Decision.** Every measure writes the same row shape to `factMeasureResult`, following CMS's population model (initial population, denominator or measure population, exclusion, exception, numerator, observation value, stratum; `expectedValue` reserved for risk adjustment). `dimMeasure.scoringType` tells `factMeasureSummary` whether to compute a rate or a median.

**Why.** A sixth measure is a `dimMeasure` row plus logic emitting standard rows: no new tables or columns. OP-22 replaced the Hybrid hospital-wide readmission measure partly because it fits this model without a risk-adjustment branch.

---

## ADR-009: Epic export from a notebook; Clarity as the fallback for daily changes
**Status:** Proposed (confirm Epic's export limits for Happy Health)

**Context.** Epic's backend login needs a JWT signed with a private key, which Fabric pipeline connectors can't create. Epic's bulk export is group-based, has no `_since` filter and by default runs once per group per day.

**Decision.** A plain Python notebook does the export (token, kick-off, polling, download); the pipeline only schedules and monitors it. If daily volumes or limits make bulk export unsuitable, daily changes come from Epic Clarity through Fabric mirroring, with a separate mapping into silver.

**Watch.** Notebooks can't use the on-premises data gateway; an internal-only Epic endpoint needs a private network path.

---

## ADR-010: Star schema in gold, Direct Lake with a fixed identity
**Status:** Accepted

**Decision.** Gold quality tables form a star (facts per event grain, conformed dimensions). Semantic models use Direct Lake with a fixed identity, so report users need no lakehouse access; roles live in the model and in Git.

**Why.** Fits Power BI best; users can't bypass row-level security through OneLake or the SQL endpoint. SQL-endpoint row-level security is avoided on Direct Lake tables because it forces DirectQuery fallback.

---

## ADR-011: De-identification by Safe Harbor rules plus Presidio
**Status:** Accepted

**Decision.** Approved column list per study; deterministic Safe Harbor rules for structured fields (`src/happy_platform/deid.py`); Presidio for free text; random study IDs with the crosswalk in a restricted lakehouse; automated release checks; privacy-officer sign-off. Exact dates need Expert Determination or a limited data set under a data use agreement.

---

## ADR-012: Capacity: F64 for production, on-demand Spark for heavy jobs
**Status:** Proposed (validate with the pilot's Capacity Metrics data)

**Decision.** Production F64 with autoscale billing for Spark, so nightly notebooks don't consume the capacity reports use. UAT F32, raised to F64 for the parallel run (weeks 12–14); dev F8, paused out of hours, synthetic data only. Reserve capacity after one to two months of pay-as-you-go.

**Why.** About 500 report viewers: from F64 up they need only a free license, which is cheaper than Pro licenses for all of them. Direct Lake on F64 allows 25 GB and 1.5 billion rows per table, enough for the quality models.

**Costs.** About $8,300 a month in total (see [workspace-and-capacity.md](workspace-and-capacity.md)). The full five-year lab history (about 2.5 billion rows) doesn't fit one Direct Lake table on F64; models read summarized tables, or a model that needs every row moves to F128.
