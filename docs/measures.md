# Measure calculation rules

> Part of the [Happy Health Fabric platform](../README.md) documentation.

The rules below are exactly what [`src/happy_platform/measures.py`](../src/happy_platform/measures.py) and [`notebooks/05_measure_calculation`](../notebooks/05_measure_calculation.ipynb) implement on the synthetic data. They are simplified versions of the CMS specifications for demonstration; production logic follows the specification version recorded in `dimMeasure` (code lists, planned-readmission algorithm, SEP-1 abstraction rules).

## Common rules

* **Run pinning.** The run's link version decides which person each source record belongs to; the reporting period comes from `dimCalculationRun` (end date inclusive).
* **Hospital** = first three characters of the location key (`H13-IP` → `H13`). Readmissions count at the index hospital.
* **Rounding** is half-up (as in Excel and Spark's `round`), on exact elapsed time: minutes to whole numbers, sepsis hours to 2 decimals (discharge hours to 1), readmission days to 1 decimal.
* **Initial population** = the event falls in the reporting period. **Exclusion** = in the initial population but excluded, with a reason. Rows outside the period keep their reason text but aren't counted as exclusions.
* **Parameters** (versioned in the MDM source): 30-day window, minimum age 18, SEP-1 bundles at 3 and 6 hours, lactate 2 (repeat) and 4 (fluids), 30 mL/kg crystalloid.

## 1. READM-30 – 30-day readmission (proportion, lower is better)

| Step | Rule |
|---|---|
| Events | Inpatient stays in `factVisit` |
| Initial population | Discharged in the period |
| Exclusions (in order) | Age at admission under 18 · died in hospital · transferred to another acute hospital · left against medical advice |
| Numerator | The same **person** (resolved at the run's link version) has an unplanned inpatient admission at any Happy Health hospital, Epic or MEDITECH, within 30 days of discharge |
| Observation | Days to the next unplanned admission (information only) |

## 2. SEP-1 – sepsis bundle (proportion, all-or-nothing)

| Step | Rule |
|---|---|
| Events | Episodes in `factSepsisEpisode`; hours measured from time zero |
| Initial population | Time zero in the period |
| Exclusions (in order) | Under 18 · transferred in from another acute hospital · comfort care within 6 h · discharged within 6 h |
| Numerator | Every element met: initial lactate ≤ 3 h; blood cultures before antibiotics and ≤ 3 h; antibiotics ≤ 3 h; repeat lactate ≤ 6 h if the first was above 2; 30 mL/kg crystalloid ≤ 3 h for septic shock or lactate ≥ 4; vasopressors ≤ 6 h if low blood pressure persisted |

## 3. ED-T2P – time to provider (continuous variable, internal; former OP-20)

| Step | Rule |
|---|---|
| Events | ED visits in `factEdVisit` |
| Initial population | Arrival in the period |
| Exclusion | Left without being seen (no provider-seen time) |
| Observation | Minutes from arrival to provider; result = median |

## 4. OP-18 – arrival to departure, discharged patients (continuous variable, two strata)

| Step | Rule |
|---|---|
| Initial population | ED arrival in the period |
| Exclusion | Not discharged (admitted, transferred, left without being seen, left against advice) |
| Strata | OP-18c mental health: the visit has a diagnosis in ICD-10-CM chapter F; OP-18b main: all others |
| Observation | Minutes from arrival to departure; result = median per stratum |

## 5. OP-22 – left without being seen (proportion, lower is better)

| Step | Rule |
|---|---|
| Denominator | Every ED visit arriving in the period |
| Numerator | Disposition = left without being seen |

## Results on the synthetic data

| Measure | R-2026Q3-01 (link version 7, submitted) | R-2026Q3-02 (link version 8, draft) |
|---|---|---|
| READM-30 | 6 / 42 = **14.3%** | 5 / 42 = **11.9%** |
| SEP-1 | 5 / 10 = **50%** | 50% |
| ED-T2P | median **46.5 min** (38 visits) | 46.5 min |
| OP-18b main | median **207 min** (26 visits) | 207 min |
| OP-18c mental health | median **127.5 min** (2 visits) | 127.5 min |
| OP-22 | 3 / 41 = **7.3%** | 7.3% |

The only difference between the runs is identity: in link version 8 the steward split MEDI-88012 from P-0012, so a MEDITECH admission no longer counts as that patient's readmission. Submitted run R-2026Q3-01 stays frozen; R-2026Q3-02 sits beside it with the difference explained.

`tests/test_measures.py` checks the reference implementation against all 193 patient-level rows and all 91 summary rows of the workbook ([`samples/HappyHealth_CMS_Measures_Synthetic_Data.xlsx`](../samples/HappyHealth_CMS_Measures_Synthetic_Data.xlsx)), and that run 02 gives 11.9%.

## Adding a measure

1. Add a `dimMeasure` row: measure ID, specification version, scoring type, strata, effective dates.
2. Add its code lists to reference data.
3. Write logic that emits standard `factMeasureResult` rows (one function in `measures.py`, one block in notebook 05).
4. If the scoring type is new (for example risk-adjusted, using `expectedValue`), add one branch to the summary.
5. Add the expected results for the synthetic data to the tests.

CMS's Emergency Care Access & Timeliness measure (voluntary 2027, mandatory 2028, replacing OP-18 and OP-22) reuses `factEdVisit` as it is: room-assigned, boarding and length-of-stay times are already there.
