"""Export the synthetic workbook into the repository's sample layers.

gold/   star schema tables exactly as in the workbook
silver/ FHIR-shaped conformed tables (the shape the gold build reads), plus the identity tables
reference/expected_results.json  the workbook's Summary results, used by the tests

Usage: python tools/export_samples.py <workbook.xlsx> <repo root>
"""
import csv, json, sys
from datetime import datetime, date
from pathlib import Path
from openpyxl import load_workbook

WB, ROOT = sys.argv[1], Path(sys.argv[2])
wb = load_workbook(WB, data_only=True)

def rows(name):
    ws = wb[name]
    hdr = [c.value for c in ws[4]]
    out = []
    for r in ws.iter_rows(min_row=5, values_only=True):
        if r[0] is None:
            break
        out.append(dict(zip(hdr, r)))
    return out

def fmt(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)

DATE_ONLY = {"birthDate", "date", "effectiveFrom", "effectiveTo", "validFrom"}

def write(path, data, cols=None, date_only=DATE_ONLY):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or list(data[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in data:
            out = []
            for c in cols:
                v = r.get(c)
                if isinstance(v, datetime) and c in date_only:
                    out.append(v.date().isoformat())
                else:
                    out.append(fmt(v))
            w.writerow(out)
    print(f"{path.relative_to(ROOT)}: {len(data)} rows")

# ---------------- gold: star schema as in the workbook
GOLD = ["factVisit", "factEdVisit", "factSepsisEpisode", "bridgeDiagnosis", "dimMeasure", "dimCalculationRun",
        "dimDateTime", "dimLocation", "dimPractitioner", "dimPayer", "factMeasureResult", "factMeasureSummary"]
for t in GOLD:
    data = rows(t)
    if t == "dimMeasure":
        for r in data:
            r.pop("calcSheet", None)
    write(ROOT / "samples/gold" / f"{t}.csv", data,
          date_only=DATE_ONLY | ({"periodStart", "periodEnd"} if t == "dimCalculationRun" else set()))

# ---------------- silver identity (shared with gold through a OneLake shortcut)
for t in ["dimPatientSource", "dimPerson", "bridgePatientLinkHistory"]:
    write(ROOT / "samples/silver/identity" / f"{t}.csv", rows(t))

# ---------------- silver clinical: FHIR-shaped conformed tables
src = rows("dimPatientSource")
write(ROOT / "samples/silver/clinical/patient.csv", [{
    "patientId": r["sourcePatientKey"], "sourceSystem": r["sourceSystem"], "localRecordNumber": r["localRecordNumber"],
    "givenName": r["firstName"], "familyName": r["lastName"], "birthDate": r["birthDate"],
    "gender": {"M": "male", "F": "female"}.get(r["sex"], "unknown"), "postalCode": r["zip"]} for r in src])

vis = rows("factVisit")
write(ROOT / "samples/silver/clinical/encounter.csv", [{
    "encounterId": r["visitKey"], "sourceSystem": r["sourceSystem"], "patientId": r["sourcePatientKey"],
    "encounterClass": {"Inpatient": "IMP", "Emergency": "EMER"}[r["patientClass"]], "locationId": r["locationKey"],
    "periodStart": r["admitDateTime"], "periodEnd": r["dischargeDateTime"], "dischargeDisposition": r["dischargeDisposition"],
    "admissionType": "elective" if r["plannedAdmission"] == "Y" else "emergency", "coverageId": r["payerKey"],
    "attendingPractitionerId": r["attendingPractitionerKey"]} for r in vis])

ed = rows("factEdVisit")
write(ROOT / "samples/silver/clinical/edTrackingEvent.csv", [{
    "edTrackingId": r["edVisitKey"], "encounterId": r["visitKey"], "triageDateTime": r["triageDateTime"],
    "providerSeenDateTime": r["providerSeenDateTime"], "roomAssignedDateTime": r["roomAssignedDateTime"],
    "decisionToAdmitDateTime": r["decisionToAdmitDateTime"], "edDisposition": r["edDisposition"],
    "admittedEncounterId": r["admittedVisitKey"]} for r in ed])

dx = rows("bridgeDiagnosis")
write(ROOT / "samples/silver/clinical/condition.csv", [{
    "encounterId": r["visitKey"], "icd10Code": r["dxCode"], "display": r["dxDescription"],
    "diagnosisRole": "principal" if r["dxType"] == "Principal" else "secondary"} for r in dx])

sep = rows("factSepsisEpisode")
write(ROOT / "samples/silver/clinical/sepsisEpisode.csv", [{**{"sepsisEpisodeId": r["episodeKey"], "encounterId": r["visitKey"]},
    **{k: v for k, v in r.items() if k not in ("episodeKey", "visitKey", "sourcePatientKey")}} for r in sep])

# ---------------- reference results for the tests (Summary sheet = run R-2026Q3-01)
s = wb["Summary"]
exp = []
for r in range(5, 11):
    mid = s.cell(r, 1).value
    if not mid:
        continue
    exp.append({"measureId": mid, "stratum": s.cell(r, 4).value, "initialPopulation": s.cell(r, 5).value,
                "exclusions": s.cell(r, 6).value, "denominatorOrMeasurePop": s.cell(r, 7).value,
                "numeratorOrMedian": s.cell(r, 8).value, "resultValue": s.cell(r, 9).value})
summ = rows("factMeasureSummary")
(ROOT / "samples/reference").mkdir(parents=True, exist_ok=True)
json.dump({"runId": "R-2026Q3-01", "linkVersion": 7, "summary": exp,
           "byHospital": [{k: summ_r[k] for k in ("runId", "measureId", "hospital", "stratum", "initialPopulation", "exclusions",
                                                 "denominatorOrMeasurePop", "numerator", "observationMedian", "resultValue")} for summ_r in summ]},
          open(ROOT / "samples/reference/expected_results.json", "w"), indent=1, default=str)
print("reference: expected_results.json")
