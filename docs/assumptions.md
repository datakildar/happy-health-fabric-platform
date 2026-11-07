# Assumptions and open questions

> Part of the [Happy Health Fabric platform](../README.md) documentation.


## What we assumed, and what we'd confirm in week one

*What we assumed, and what we'd confirm with stakeholders in week one*

**Assumptions**

- MEDITECH nightly files are extended with pharmacy orders and doses, coded diagnoses and procedures, and emergency department tracking events
- Epic's bulk FHIR export can refresh daily within its group limits; otherwise daily changes come from Epic Clarity through mirroring
- MEDITECH HL7 export stays nightly for the 120 days
- Last quarter's spreadsheets can be used for a side-by-side check
- A named requirements owner has the authority to answer questions and confirm changes

**Open questions for week one**

- Can the MEDITECH interface team deliver the MEDITECH additions in time, and at what cost?
- Who owns patient identity and the matching thresholds today?
- Where do care manager panel assignments come from?
- Does the research study need exact dates? Safe Harbor keeps only the year
- Why not use MEDITECH's FHIR interface to get near-real-time data from the newly acquired hospitals?
- What platform does each ancillary system run on? Are any of them SQL Server or Oracle databases that Fabric can mirror natively?
- Do any sources carry Social Security numbers (full or last four digits), and will the privacy officer allow their use in matching?

The problem statement is deliberately underspecified, so we state what we assumed and what we'd confirm in week one rather than guess.

Assumptions. First, the MEDITECH nightly files will be extended with three additions: pharmacy orders and doses given, coded diagnoses and procedures, and emergency department tracking events. Without them, SEP-1 and time to provider can't be fully calculated at the five MEDITECH hospitals. Our fallback is for abstractors to fill a structured template that is loaded into the pipeline. Second, Epic's bulk FHIR export can refresh daily within its limits (group-based, no changed-since filter, once per group per day by default); otherwise daily changes come from Epic's Clarity reporting database through mirroring. Third, MEDITECH stays on nightly files for the full 120 days. Fourth, last quarter's spreadsheets can serve as the baseline for a side-by-side check. Fifth, a named requirements owner has the authority to answer questions and confirm changes, so decisions don't stall.

Open questions. Can the MEDITECH interface team deliver the MEDITECH additions in time, and what does the contract allow? Who owns patient identity today, usually Health Information Management, and who should approve threshold changes? Where do care manager panel assignments live? Do any sources carry Social Security numbers, full or only the last four digits, and will the privacy officer allow them to be used for matching? The problem statement's source reference doesn't list them in any source. For research, which data items and how precise do dates need to be? Safe Harbor removes all dates except the year, which may not suit an outcomes study. If not, Expert Determination is the alternative to raise. Finally: who handles the research ethics approval and the data use agreement?

Two more questions shape ingestion. First, why not use MEDITECH's FHIR interface for near-real-time data from the newly acquired hospitals? MEDITECH Expanse offers FHIR APIs, while older MEDITECH platforms may not. If the acquired hospitals run Expanse and the APIs can be licensed and enabled, they would give fresher data in the same format as Epic and remove the HL7v2 conversion step. We didn't plan on it because the problem statement says the hospitals are batch-only with no funded interface project, but because everything is converted to FHIR, switching later is a small change. Second, what platform does each ancillary system run on? Fabric mirroring is generally available for SQL Server 2016 to 2025 and supports Oracle 10 and later (confirm whether Oracle mirroring is still in preview), both through the on-premises gateway. Mirroring keeps a near-real-time copy in OneLake with no pipeline to maintain, so the answer decides between mirroring and scheduled pipeline copies for each system.
