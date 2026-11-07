# Field-level lineage
> Part of the [Happy Health Fabric platform](../README.md) documentation.

Every gold field traced to its silver (FHIR) element and its Epic, MEDITECH and other sources. Silver stores hospital local time (America/New_York).

## factVisit

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| visitKey | Visit identifier | Epic + MEDITECH | Encounter.id / Encounter.identifier | Encounter.id | ADT PV1-19 Visit / account number → Encounter.identifier |  | Surrogate key: source system + encounter ID (VIS-n in the workbook) |
| sourcePatientKey | Patient record in the source system | Epic + MEDITECH | Encounter.subject → Patient.id | Encounter.subject (Patient/{id}) | ADT PID-3 Patient identifier list (MRN) → Patient.identifier |  | Prefix with source system: EPIC-… / MEDI-… |
| locationKey | Hospital and unit of the visit | Epic + MEDITECH | Encounter.location.location → Location | Encounter.location.location | ADT PV1-3 Assigned patient location (point of care, facility) | Profisee location master | Map source location to dimLocation key via the location master |
| sourceSystem | Epic or MEDITECH | Derived | Bundle / load metadata | Ingestion pipeline (Epic) | Ingestion pipeline (MEDITECH) |  | Set from the load that brought the record in |
| patientClass | Inpatient, Emergency or Outpatient | Epic + MEDITECH | Encounter.class | Encounter.class (IMP / EMER / AMB) | ADT PV1-2 Patient class (I / E / O) |  | Map codes to Inpatient / Emergency / Outpatient |
| admitDateTime | Start of the visit | Epic + MEDITECH | Encounter.period.start | Encounter.period.start | ADT PV1-44 Admit date/time |  | Convert to hospital local time (America/New_York) |
| dischargeDateTime | End of the visit | Epic + MEDITECH | Encounter.period.end | Encounter.period.end | ADT A03 PV1-45 Discharge date/time |  | Normalize time; open visits have no end |
| dischargeDisposition | Where the patient went (home, SNF, expired, transfer, AMA…) | Epic + MEDITECH | Encounter.hospitalization.dischargeDisposition | Encounter.hospitalization.dischargeDisposition | ADT PV1-36 Discharge disposition |  | Map local codes to the standard disposition list |
| plannedAdmission | Planned (elective) admission flag | Epic + MEDITECH | Encounter.priority | Encounter.priority (EL = elective) | ADT PV1-4 Admission type (R / elective) |  | Y if elective. Production uses the CMS planned-readmission algorithm on procedures and diagnoses |
| payerKey | Insurance for the visit | Epic + MEDITECH | Encounter.account → Account.coverage → Coverage.payor / Coverage.type | Coverage.payor, Coverage.type | ADT IN1-3 Insurance company ID, IN1-15 Plan type | Claims / billing payer master | Map to dimPayer |
| attendingPractitionerKey | Attending provider | Epic + MEDITECH | Encounter.participant (type = ATND).individual → Practitioner | Encounter.participant.individual | ADT PV1-7 Attending doctor (XCN) | Profisee provider master (NPI) | Map to dimPractitioner via national provider ID |
| principalDxCode | Main diagnosis (ICD-10-CM) | Epic + MEDITECH | Encounter.diagnosis (rank = 1).condition → Condition.code | Encounter.diagnosis.condition → Condition.code | ADT DG1-3 Diagnosis code where DG1-15 Priority = 1 (new DG1 segments) | Claims system (final coded diagnoses) | Prefer final coded diagnosis; ICD-10-CM codes |

## bridgeDiagnosis

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| visitKey | Visit the diagnosis belongs to | Epic + MEDITECH | Encounter.diagnosis → Encounter.id | Encounter.diagnosis | DG1 segments in the visit's ADT message |  | Same key rule as factVisit.visitKey |
| dxCode | Diagnosis code | Epic + MEDITECH | Condition.code.coding (ICD-10-CM) | Condition.code | DG1-3 Diagnosis code | Claims ICD-10 lines | Keep ICD-10-CM coding only |
| dxDescription | Diagnosis name | Reference | Condition.code.coding.display | Condition.code.coding.display | DG1-4 Diagnosis description | ICD-10-CM code list | Taken from the official code list for consistency |
| dxType | Principal or secondary | Epic + MEDITECH | Encounter.diagnosis.rank / .use | Encounter.diagnosis.rank | DG1-15 Diagnosis priority / DG1-6 Diagnosis type |  | rank 1 = Principal, others = Secondary |
| isMentalHealth | Mental health diagnosis flag (OP-18 stratum) | Derived |  |  |  |  | 1 if the ICD-10-CM code starts with F |

## factEdVisit

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| edVisitKey | ED visit identifier | Epic + MEDITECH | Encounter.id (class = EMER) | Encounter.id | ADT A04 PV1-19 Visit number |  | Surrogate key (ED-n in the workbook) |
| visitKey | Matching visit row in factVisit | Derived |  |  |  |  | Same encounter as the factVisit row with patientClass = Emergency |
| sourcePatientKey | Patient record in the source system | Epic + MEDITECH | Encounter.subject → Patient.id | Encounter.subject | PID-3 (MRN) |  | Prefix EPIC- / MEDI- |
| locationKey | Emergency department | Epic + MEDITECH | Encounter.location.location | Encounter.location.location | PV1-3 Assigned patient location | Profisee location master | Map to dimLocation |
| arrivalDateTime | ED arrival | Epic + MEDITECH | Encounter.period.start | Encounter.period.start | ADT A04 PV1-44 Admit date/time (EVN-6 event occurred) |  | Normalize time |
| triageDateTime | Triage time | Epic + MEDITECH | Encounter.statusHistory (status = triaged).period.start | Encounter.statusHistory | ED tracking event (new FirstNet feed: triage) |  | First triage event |
| providerSeenDateTime | First provider contact | Epic + MEDITECH | Encounter.participant (ED provider).period.start | Encounter.participant.period.start | ED tracking event: ROL-3 role (ED physician / APP), ROL-5 role begin date/time (new) |  | First ED provider assignment; blank if left before being seen |
| roomAssignedDateTime | Treatment room assigned | Epic + MEDITECH | Encounter.location (room).period.start | Encounter.location.period.start | ADT A02 Transfer: PV1-3 room/bed change, EVN-6 |  | First move into an ED treatment room |
| decisionToAdmitDateTime | Decision to admit | Epic + MEDITECH | ServiceRequest (admission order).authoredOn | ServiceRequest.authoredOn | ADT A14 Pending admit (EVN-6) or admit order ORC-9 |  | Earliest admit decision; only for admitted visits |
| departureDateTime | Left the ED | Epic + MEDITECH | Encounter.period.end | Encounter.period.end | ADT A03 PV1-45 or A02 transfer to inpatient (EVN-6) |  | Normalize time |
| edDisposition | Discharged, admitted, transferred, LWBS, AMA | Epic + MEDITECH | Encounter.hospitalization.dischargeDisposition | Encounter.hospitalization.dischargeDisposition | PV1-36 Discharge disposition |  | Map local codes to the five dispositions |
| admittedVisitKey | Inpatient visit created from this ED visit | Epic + MEDITECH | Encounter.partOf / shared Encounter.account | Encounter.partOf or Encounter.account | Same PV1-19 visit / account number on the inpatient ADT A01/A06 |  | Link ED and inpatient encounters |

## factSepsisEpisode

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| episodeKey | Sepsis episode identifier | Derived |  |  |  |  | Generated by the sepsis logic, one per qualifying episode |
| visitKey | Inpatient visit | Epic + MEDITECH | Encounter.id | Encounter.id | PV1-19 |  | Same key rule as factVisit |
| sourcePatientKey | Patient record | Epic + MEDITECH | Patient.id | Encounter.subject | PID-3 |  | Prefix EPIC- / MEDI- |
| timeZero | Severe sepsis presentation time | Derived | Observation, Condition, MedicationAdministration | Vital-sign and lab Observations; Condition | ORU OBX results; DG1 | Abstractor confirmation | SEP-1 rules: infection suspected + SIRS + organ dysfunction within the window; abstractor confirms from notes |
| severity | Severe sepsis or septic shock | Derived | Condition.code / Observation | Condition.code (R65.20 / R65.21) | DG1-3 |  | Septic shock if lactate ≥ 4 or hypotension; else severe sepsis |
| initialLactateTime / initialLactateValue | First lactate result | Epic + MEDITECH | Observation (LOINC 2524-7, 32693-4).effectiveDateTime / .valueQuantity | Observation.effectiveDateTime, .valueQuantity | ORU OBX-3 (LOINC), OBX-5 value, OBR-7 collection time | Laboratory system (LIS) | First lactate around time zero; units mmol/L |
| bloodCultureTime | Blood culture collected | Epic + MEDITECH | Specimen.collection.collectedDateTime (blood culture, LOINC 600-7) | Specimen.collection.collectedDateTime | ORU microbiology OBR-7 / SPM-17 collection date/time | Laboratory system (LIS) | First blood culture collection |
| antibioticStartTime | First broad-spectrum antibiotic given | Epic + MEDITECH | MedicationAdministration.effectiveDateTime (antibiotic code list) | MedicationAdministration | RAS RXA-3 Start of administration, RXA-5 drug (new pharmacy feed) | Pharmacy system | First dose from the SEP-1 antibiotic code list (VSAC) |
| repeatLactateTime | Repeat lactate | Epic + MEDITECH | Observation (lactate) second result | Observation | ORU OBX / OBR-7 | Laboratory system (LIS) | Next lactate after the initial one |
| weightKg | Patient weight | Epic + MEDITECH | Observation (LOINC 29463-7).valueQuantity | Observation | ORU or ADT OBX (body weight) |  | Weight closest to time zero, in kg |
| crystalloidVolumeMl / crystalloidStartTime | IV fluids given | Epic + MEDITECH | MedicationAdministration.dosage.dose / .effectivePeriod.start (crystalloid code list) | MedicationAdministration | RAS RXA-6 amount, RXA-7 units, RXA-3 start (new) | Pharmacy system | Sum crystalloid volume in the window; first start time |
| persistentHypotension | Low blood pressure after fluids | Derived | Observation (LOINC 8480-6 systolic, 8478-0 mean BP) | Observation | ORU OBX vital signs |  | Y if systolic < 90 or mean < 65 persists after the fluids |
| vasopressorStartTime | First vasopressor given | Epic + MEDITECH | MedicationAdministration (vasopressor code list).effectiveDateTime | MedicationAdministration | RAS RXA-3, RXA-5 (new) | Pharmacy system | First dose from the vasopressor code list |
| transferInFromAcute | Arrived as a transfer from another hospital | Epic + MEDITECH | Encounter.hospitalization.admitSource | Encounter.hospitalization.admitSource (hosp-trans) | PV1-14 Admit source |  | Y if transferred from another acute hospital (exclusion) |
| comfortCareTime | Comfort measures ordered | Epic + MEDITECH | ServiceRequest (comfort care order).authoredOn | ServiceRequest.authoredOn | Order message ORC-9 (comfort care order) | Abstractor confirmation | Earliest comfort-care order (exclusion if within 6 h) |

## dimPatientSource

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| sourcePatientKey | Patient record key | Epic + MEDITECH | Patient.id | Patient.id | PID-3 | LIS / pharmacy / scheduling local IDs; claims subscriber ID | Prefix with source system |
| sourceSystem | System holding the record | Derived |  | Load metadata | Load metadata |  |  |
| localRecordNumber | Medical record number | Epic + MEDITECH | Patient.identifier (type = MR) | Patient.identifier | PID-3.1 ID number |  |  |
| firstName / lastName | Patient name | Epic + MEDITECH | Patient.name.given / Patient.name.family | Patient.name | PID-5.2 given / PID-5.1 family |  | Standardize case and spacing for matching |
| birthDate | Date of birth | Epic + MEDITECH | Patient.birthDate | Patient.birthDate | PID-7 |  | Placeholder dates flagged for matching |
| sex | Administrative sex | Epic + MEDITECH | Patient.gender | Patient.gender | PID-8 |  | Map to F / M / other / unknown |
| zip | Home ZIP code | Epic + MEDITECH | Patient.address.postalCode | Patient.address.postalCode | PID-11.5 |  | Address standardized (USPS) before matching |

## dimPerson

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| personId / personNum | Enterprise person ID | Derived |  |  |  | Splink matching (Fabric notebook) | Created when a new cluster forms; never reused |
| status / forwardedTo | Active or retired; surviving person after a merge | Derived |  |  |  | Splink + steward decisions | Retired IDs forward to the surviving person |

## bridgePatientLinkHistory

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| sourcePatientKey → personId | Which person a source record belongs to | Derived |  |  |  | Splink cluster output + HIM steward review queue | One row per link; a change ends the old row and adds a new one |
| versionFrom / versionTo | Link versions in which the row is true | Derived |  |  |  | Identity release control table | Set when matching publishes a new version |
| validFrom / recordedAt | Real-world start / when we learned it | Derived |  |  |  | Splink run time; steward decision time |  |
| linkMethod / matchProbability | How linked; Splink match probability | Derived |  |  |  | Splink (match_probability); steward | Exact / Scored / Steward |
| mdmSettingsVersion | Threshold settings used | MDM |  |  |  | MDM settings (Profisee) |  |

## dimLocation

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| locationKey, hospital, unit, unitType | Hospital and unit | Epic + MEDITECH | Location.id, .name, .type, .partOf / .managingOrganization | Location resource | PV1-3 point of care, room, bed, facility | Profisee location master | Mastered so Epic and MEDITECH units line up |
| sourceSystem | Epic or MEDITECH | Derived |  |  |  |  |  |

## dimPractitioner

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| practitionerKey, name | Provider | Epic + MEDITECH | Practitioner.id, Practitioner.name | Practitioner | PV1-7 Attending doctor (XCN: ID, family, given) | Profisee provider master |  |
| specialty | Specialty | Epic + MEDITECH | PractitionerRole.specialty | PractitionerRole.specialty |  | National provider registry (NPPES) |  |
| nationalProviderId | National provider ID (NPI) | Epic + MEDITECH | Practitioner.identifier (system = us-npi) | Practitioner.identifier | PV1-7.1 ID (mapped to NPI) | National provider registry (NPPES) | Match key across Epic and MEDITECH |

## dimPayer

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| payerKey, payerName, payerType | Insurance | Epic + MEDITECH | Coverage.payor → Organization.name; Coverage.type | Coverage | IN1-3 company ID, IN1-4 company name, IN1-15 plan type | Claims / billing payer master | Grouped into Medicare FFS, Medicare Advantage, Medicaid, Commercial, Self-pay |

## dimMeasure

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| all fields | Measure catalog | Reference |  |  |  | CMS specifications (eCQI Resource Center, QualityNet manuals); code lists from VSAC | Maintained by the measure catalog owner (Quality / CoE); one row per spec version |

## dimCalculationRun

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| runId, runDateTime, status | Calculation run | Derived |  |  |  | Fabric Pipelines run metadata | Created at the start of each measure run |
| periodStart / periodEnd | Reporting period | Derived |  |  |  | Run parameters |  |
| linkVersion | Patient-link version pinned for the run | Derived |  |  |  | Identity release control table | Latest published version when the run starts |
| mdmSettingsVersion / codeVersion | Settings and code versions | MDM |  |  |  | MDM settings; Git tag of the measure code |  |

## dimDateTime

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| all fields | Calendar | Derived |  |  |  | Generated calendar | inReportingPeriod compares with the selected run |

## factMeasureResult

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| resultKey | Result row key | Derived |  |  |  | Measure logic | Generated |
| runId | Calculation run | Derived |  |  |  | dimCalculationRun | The run being calculated |
| measureKey / measureId | Measure | Derived |  |  |  | dimMeasure |  |
| scoringType | Proportion or continuous variable | Derived |  |  |  | dimMeasure.scoringType | Lookup |
| reportingPeriod | Year and quarter | Derived |  |  |  | dimCalculationRun.periodStart | Calculated |
| hospital | Hospital of the event | Derived |  |  |  | factVisit / factEdVisit.locationKey → dimLocation | First 3 characters of the location key |
| sourcePatientKey | Patient record | Derived |  |  |  | Event fact |  |
| eventKey | Visit, ED visit or sepsis episode | Derived |  |  |  | Event fact |  |
| stratum | Reporting group | Derived |  |  |  | Measure logic (OP-18: bridgeDiagnosis mental health flag) |  |
| inInitialPopulation | In scope for the period | Derived |  |  |  | Calc sheets (inPeriod column) |  |
| inDenominatorOrMeasurePop | Denominator / measure population | Derived |  |  |  | Calc sheets (inDenominator / inMeasurePopulation) |  |
| isExclusion / exclusionReason | Excluded and why | Derived |  |  |  | Calc sheets (exclusionReason) | 1 if in scope and a reason exists |
| isException | Exception | Derived |  |  |  | Measure logic | 0: none of these measures has exceptions |
| inNumerator | Met the numerator | Derived |  |  |  | Calc sheets (readmitted / all elements met / left without being seen) | Empty for continuous-variable measures |
| observationValue / observationUnit | Minutes or days | Derived |  |  |  | Calc sheets (minutes / days columns) |  |
| expectedValue | Predicted risk | Derived |  |  |  | Reserved | Empty: no risk-adjusted measure in this set |

## factMeasureSummary

| Field | Description | Source type | Silver (FHIR) | Epic FHIR R4 | MEDITECH HL7v2 | Other source | Transformation |
|---|---|---|---|---|---|---|---|
| counts (initialPopulation, exclusions, denominatorOrMeasurePop, numerator) | Population counts | Derived |  |  |  | factMeasureResult | COUNTIFS by measure, hospital and stratum |
| observationMedian | Median of observations | Derived |  |  |  | factMeasureResult.observationValue | MEDIAN over the measure population (continuous variable) |
| resultValue / calculationApplied | Measure result | Derived |  |  |  | dimMeasure.scoringType + counts / median | Proportion = numerator ÷ denominator; continuous variable = median |

