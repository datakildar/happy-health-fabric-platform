"""Generate the bronze samples from the silver samples.

samples/bronze/epic_fhir/      Patient, Encounter, Condition as FHIR R4 NDJSON (what an Epic bulk export returns)
samples/bronze/meditech_hl7v2/   nightly batch files of ADT^A03 messages, one file per discharge date

Run after export_samples.py:  python tools/make_bronze.py <repo root>
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from happy_platform.fhir_flatten import COVERAGE_EXT, ED_EXT, MRN_SYSTEM  # noqa: E402
from happy_platform.hl7v2 import DISPOSITION_CODE  # noqa: E402
from happy_platform.samples import load_silver_clinical  # noqa: E402

ROOT = Path(sys.argv[1])
TZ = ZoneInfo("America/New_York")
s = load_silver_clinical()
pat, enc, ed, cond = s["patient"], s["encounter"], s["edTrackingEvent"], s["condition"]
ed_by_enc = {r.encounterId: r for r in ed.itertuples()}
inst = lambda d: d.replace(tzinfo=TZ).isoformat() if d is not None else None       # local time -> FHIR instant with offset

# ---------------------------------------------------------------- Epic: FHIR R4 NDJSON
out = ROOT / "samples/bronze/epic_fhir"
out.mkdir(parents=True, exist_ok=True)
epic_pat = pat[pat["sourceSystem"] == "Epic"]
fhir_id = {r.patientId: f"e{r.localRecordNumber}a" for r in epic_pat.itertuples()}    # opaque FHIR ids, as Epic returns
with open(out / "Patient.ndjson", "w") as f:
    for r in epic_pat.itertuples():
        f.write(json.dumps({"resourceType": "Patient", "id": fhir_id[r.patientId],
                            "identifier": [{"type": {"text": "MRN"}, "system": MRN_SYSTEM, "value": r.localRecordNumber}],
                            "name": [{"use": "official", "family": r.familyName, "given": [r.givenName]}],
                            "gender": r.gender, "birthDate": r.birthDate.isoformat(), "address": [{"postalCode": r.postalCode}]}) + "\n")

epic_enc = enc[enc["sourceSystem"] == "Epic"]
cond_ids = {}
with open(out / "Condition.ndjson", "w") as f:
    for i, r in enumerate(cond[cond["encounterId"].isin(epic_enc["encounterId"])].itertuples(), 1):
        cid = f"c{i:05d}"
        cond_ids.setdefault(r.encounterId, []).append((cid, r.diagnosisRole))
        e = epic_enc[epic_enc["encounterId"] == r.encounterId].iloc[0]
        f.write(json.dumps({"resourceType": "Condition", "id": cid,
                            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "encounter-diagnosis"}]}],
                            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": r.icd10Code, "display": r.display}]},
                            "subject": {"reference": f"Patient/{fhir_id[e['patientId']]}"},
                            "encounter": {"reference": f"Encounter/x{r.encounterId[4:]}"}}) + "\n")

with open(out / "Encounter.ndjson", "w") as f:
    for r in epic_enc.itertuples():
        res = {"resourceType": "Encounter", "id": f"x{r.encounterId[4:]}",
               "identifier": [{"system": "urn:happy:epic:encounter-id", "value": r.encounterId}],
               "status": "finished",
               "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": r.encounterClass},
               "priority": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                                        "code": "EL" if r.admissionType == "elective" else "EM"}]},
               "subject": {"reference": f"Patient/{fhir_id[r.patientId]}"},
               "participant": [{"type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "code": "ATND"}]}],
                                "individual": {"reference": f"Practitioner/{r.attendingPractitionerId}"}}],
               "period": {"start": inst(r.periodStart), "end": inst(r.periodEnd)},
               "diagnosis": [{"condition": {"reference": f"Condition/{cid}"}, "rank": 1 if role == "principal" else 2}
                             for cid, role in cond_ids.get(r.encounterId, [])],
               "hospitalization": {"dischargeDisposition": {"text": r.dischargeDisposition}},
               "location": [{"location": {"reference": f"Location/{r.locationId}"}}],
               "extension": [{"url": COVERAGE_EXT, "valueReference": {"reference": f"Coverage/{r.coverageId}"}}]}
        t = ed_by_enc.get(r.encounterId)
        if t:
            sub = [{"url": "trackingId", "valueString": t.edTrackingId}]
            for k, v in [("triage", t.triageDateTime), ("providerSeen", t.providerSeenDateTime),
                         ("roomAssigned", t.roomAssignedDateTime), ("decisionToAdmit", t.decisionToAdmitDateTime)]:
                if v is not None:
                    sub.append({"url": k, "valueDateTime": inst(v)})
            sub.append({"url": "disposition", "valueString": t.edDisposition})
            if t.admittedEncounterId:
                sub.append({"url": "admittedEncounter", "valueString": t.admittedEncounterId})
            res["extension"].append({"url": ED_EXT, "extension": sub})
        f.write(json.dumps(res) + "\n")
print("epic:", len(epic_pat), "patients,", len(epic_enc), "encounters")

# ---------------------------------------------------------------- MEDITECH: HL7v2 ADT^A03 batch files
out = ROOT / "samples/bronze/meditech_hl7v2"
out.mkdir(parents=True, exist_ok=True)
h = lambda d: d.strftime("%Y%m%d%H%M") if d is not None else ""
med_pat = {r.patientId: r for r in pat[pat["sourceSystem"] == "MEDITECH"].itertuples()}
by_day: dict[str, list[str]] = {}
for n, r in enumerate(enc[enc["sourceSystem"] == "MEDITECH"].sort_values("periodEnd").itertuples(), 1):
    p = med_pat[r.patientId]
    sent = r.periodEnd.replace(hour=23, minute=55)
    hosp = r.locationId[:3]
    segs = [
        f"MSH|^~\\&|MEDITECH|{hosp}|HAPPY_FABRIC|HAPPY|{sent.strftime('%Y%m%d%H%M%S')}||ADT^A03^ADT_A03|C{n:06d}|P|2.5.1",
        f"EVN|A03|{h(r.periodEnd)}",
        f"PID|1||{p.localRecordNumber}^^^MEDITECH^MR||{p.familyName}^{p.givenName}||{p.birthDate.strftime('%Y%m%d')}|{p.gender[0].upper()}|||^^^^{p.postalCode}",
        "PV1|1|" + "|".join([
            {"IMP": "I", "EMER": "E"}[r.encounterClass], f"{r.locationId}^^^{hosp}", "C" if r.admissionType == "elective" else "E",
            "", "", f"{r.attendingPractitionerId}^^", *[""] * 11, f"{r.encounterId}^^^MEDITECH^VN", r.coverageId,
            *[""] * 15, DISPOSITION_CODE[r.dischargeDisposition], *[""] * 7, h(r.periodStart), h(r.periodEnd)]),
    ]
    for i, c in enumerate(cond[cond["encounterId"] == r.encounterId].itertuples(), 1):
        segs.append(f"DG1|{i}||{c.icd10Code}^{c.display}^I10||||||||||||{1 if c.diagnosisRole == 'principal' else 2}")
    t = ed_by_enc.get(r.encounterId)
    if t:
        segs.append("|".join(["ZET", t.edTrackingId, h(t.triageDateTime), h(t.providerSeenDateTime), h(t.roomAssignedDateTime),
                              h(t.decisionToAdmitDateTime), t.edDisposition, t.admittedEncounterId or ""]))
    by_day.setdefault(sent.strftime("%Y%m%d"), []).append("\r".join(segs))
for day, msgs in sorted(by_day.items()):
    (out / f"meditech_adt_{day}.hl7").write_text("\r\n".join(msgs) + "\r\n")
print("meditech:", sum(len(m) for m in by_day.values()), "messages in", len(by_day), "nightly files")
