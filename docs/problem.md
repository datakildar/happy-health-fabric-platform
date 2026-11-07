# The problem: Happy Health

> Part of the [Happy Health Fabric platform](../README.md) documentation. [Download as PDF](downloads/HappyHealth_Problem_Statement.pdf).


Happy Health is a regional health system that has just closed on five hospitals that were previously run independently. It needs one data platform that serves four groups with very different needs, starting with five CMS quality measures that must be automated within 120 days.

## Quick facts

| | |
|---|---|
| Footprint | 17 hospitals, about 150 outpatient clinics, across 3 states |
| Primary EHR | Epic, at all 12 legacy hospitals and the clinics |
| Recently acquired (4 months ago) | 5 hospitals running MEDITECH. Batch-only today: nightly flat files. No funded interface project yet. |
| Ancillary systems | Standalone lab (LIS), pharmacy, scheduling and claims/billing systems, each with its own data store |
| Executive deadline | A working pipeline for the 5 priority CMS quality measures within 120 days |
| On the horizon | The board is in late-stage talks on a further acquisition, 12–18 months out. No further detail is available yet. |

## Background

The five acquired hospitals have never shared a patient identifier with the rest of Happy Health. A patient treated at both a legacy Happy Health hospital and a newly acquired one currently shows up as two unrelated patient records, in two different EHRs, with no link between them.

Four groups are waiting on a unified data platform, and each wants something different from it. The source reference at the end lists the entities each source system holds and how each one identifies a patient.

1. **Quality and regulatory reporting.** Five priority CMS quality measures are assembled by hand in spreadsheets each quarter, pulled separately from each EHR. Leadership wants them automated and auditable:
   1. **30-day readmissions** (CMS Hospital Readmissions Reduction Program method)
   2. **SEP-1** severe sepsis and septic shock bundle compliance
   3. **ED median time to provider** (former CMS OP-20, tracked with the same method)
   4. **OP-18** median time from emergency department arrival to departure, discharged patients
   5. **OP-22** share of emergency department visits that left without being seen
2. **Population health.** The ACO wants one risk-stratified view of a patient across every facility they've touched, to target care-management outreach.
3. **Self-service operational BI.** Department leaders want dashboards, such as bed utilization and ED throughput, without filing an IT ticket for every new report.
4. **An external research data mart.** A non-governmental organization (NGO) running an outcomes study wants a multi-year, de-identified extract.

> The NGO is not a Happy Health workforce member, so the extract has to be provably de-identified under HIPAA Safe Harbor, not just access-controlled.

## Constraints

- No shared patient identifier exists between the Epic and MEDITECH hospitals today.
- Access must follow HIPAA minimum-necessary. A care manager should see only their assigned panel; a quality analyst should see de-identified aggregates unless explicitly granted access to patient information.
- The 120-day deadline for the five priority measures is fixed. It is what keeps the program funded.
- This is incremental budget, not a multi-year rebuild. The plan needs to show value inside the 120 days.
- The approach should be recommended and justified, not just a list of vendor products.

## What the solution must cover

1. **Target-state architecture.** A diagram plus a walkthrough of the major layers and how data moves from each source system to each of the four consumers.
2. **Data model for quality reporting.** The logical model behind the five measures: the grain of the core fact, the dimensions, the modeling style and why. How a merged or split patient identity is reflected without silently rewriting history in a fact table that has to stand up to an audit.
3. **Assumptions and open questions.** What is assumed, and what should be confirmed with stakeholders in week one.
4. **Cross-system patient identity.** How to link a patient across Epic, MEDITECH and the ancillary systems with no shared identifier: the matching approach, how uncertain matches are handled, and what happens when two merged records turn out to be two different people.
5. **Governance and access.** How access is scoped by role and panel, and how to prove, not just assert, that the research extract meets Safe Harbor.
6. **120-day phased plan.** What ships for the five measures inside 120 days, what is deliberately deferred, and why that split is right.
7. **Risks and mitigations.** The three to five main risks of the design, and what to do about each.

## Source reference

### Epic – FHIR R4

All 12 legacy hospitals and the clinics. Resources exposed over a live API.

| Resource | Holds | Key fields |
|---|---|---|
| Patient | Demographics | id (Epic MRN), name, birth date, gender, address |
| Encounter | A visit | id, class (inpatient / outpatient / ED), period, status, subject → Patient, location |
| Condition | A diagnosis | code (ICD-10-CM), subject → Patient, encounter, onset date |
| Observation | Vitals and lab results | code (LOINC), value, effective date, subject → Patient, encounter |
| MedicationRequest | An order | medication (NDC / RxNorm), subject → Patient, encounter |
| Procedure | A performed procedure | code (CPT / HCPCS), subject → Patient, encounter |
| Practitioner | A provider | id, name, specialty |
| Location | Unit or facility | id, name, type |

### MEDITECH – nightly HL7v2 flat files

The five newly acquired hospitals. Batch only; no live API today.

| File type | Holds | Key fields |
|---|---|---|
| ADT (admit / discharge / transfer) | Demographics and visit events | MEDITECH MRN, visit / account number, admit and discharge timestamps, facility |
| ORU (observation result) | Lab and vital-sign results | MEDITECH MRN, order number, result code, value, result timestamp |
| DFT (detail financial transaction) | Billable charge events | MEDITECH MRN, account number, charge code, charge date |

MEDITECH's MRN series is local to the five acquired hospitals. It has never been cross-walked to Epic's MRN.

### Ancillary systems

Standalone and system-wide; they predate the acquisition. Each keeps its own patient ID.

| System | Core entity | Key fields | Local patient ID |
|---|---|---|---|
| LIS | Lab order / result | order number, LOINC code, specimen, result value | LIS-local ID, own series |
| Pharmacy | Prescription / dispense | drug (NDC), dose, dispense date | Pharmacy-local ID, own series |
| Scheduling | Appointment | provider, location, scheduled time, status | Scheduling-local ID; sometimes matches the EHR MRN, not guaranteed |
| Claims / billing | Claim / claim line | CPT / HCPCS, ICD-10, payer, billed amount | Insurance subscriber ID; often not the clinical MRN at all |

### Code systems

| Standard | Used for |
|---|---|
| ICD-10-CM | Diagnoses |
| CPT / HCPCS | Procedures and billing |
| LOINC | Lab and vital-sign observations |
| NDC | Drugs |
