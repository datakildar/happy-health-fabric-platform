"""Flatten FHIR R4 NDJSON (Patient, Encounter, Condition) into the silver tables.

In Fabric, Healthcare Data Solutions does this for the standard resources; this module shows the
mapping Happy Health relies on (and the extension used for ED tracking events), and it is what the tests use
to prove the bronze samples and the silver samples agree.

Times: FHIR instants carry a UTC offset; silver stores hospital local time (America/New_York), so
every instant is converted to local time and the offset dropped.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

LOCAL_TZ = ZoneInfo("America/New_York")
ED_EXT = "https://fhir.happyhealth.example/StructureDefinition/ed-tracking"      # assumed Epic ED event mapping (to confirm)
COVERAGE_EXT = "https://fhir.happyhealth.example/StructureDefinition/encounter-coverage"
MRN_SYSTEM = "urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.14"                    # illustrative Epic MRN system


def read_ndjson(path: str | Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def to_local(instant: str | None) -> datetime | None:
    if not instant:
        return None
    return datetime.fromisoformat(instant).astimezone(LOCAL_TZ).replace(tzinfo=None)


def ref_id(reference: dict | None) -> str | None:
    return reference["reference"].split("/", 1)[1] if reference else None


def flatten_patients(resources: list[dict], source_system: str = "Epic", key_prefix: str = "EPIC") -> pd.DataFrame:
    rows = []
    for p in resources:
        mrn = next(i["value"] for i in p["identifier"] if i.get("type", {}).get("text") == "MRN")
        name = p["name"][0]
        rows.append({"patientId": f"{key_prefix}-{mrn}", "sourceSystem": source_system, "localRecordNumber": mrn,
                     "givenName": name["given"][0], "familyName": name["family"], "birthDate": p["birthDate"],
                     "gender": p.get("gender", "unknown"), "postalCode": p["address"][0]["postalCode"] if p.get("address") else None})
    return pd.DataFrame(rows)


def _ext(resource: dict, url: str) -> dict | None:
    return next((e for e in resource.get("extension", []) if e["url"] == url), None)


def flatten_encounters(resources: list[dict], patient_keys: dict[str, str], source_system: str = "Epic") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (encounter, edTrackingEvent). patient_keys maps FHIR Patient.id -> silver patientId."""
    enc_rows, ed_rows = [], []
    for e in resources:
        enc_id = next(i["value"] for i in e["identifier"] if i["system"].endswith("encounter-id"))
        cov = _ext(e, COVERAGE_EXT)
        atnd = next((p for p in e.get("participant", []) if p["type"][0]["coding"][0]["code"] == "ATND"), None)
        enc_rows.append({
            "encounterId": enc_id, "sourceSystem": source_system, "patientId": patient_keys[ref_id(e["subject"])],
            "encounterClass": e["class"]["code"], "locationId": ref_id(e["location"][0]["location"]),
            "periodStart": to_local(e["period"]["start"]), "periodEnd": to_local(e["period"].get("end")),
            "dischargeDisposition": e.get("hospitalization", {}).get("dischargeDisposition", {}).get("text"),
            "admissionType": {"EL": "elective", "EM": "emergency"}[e["priority"]["coding"][0]["code"]],
            "coverageId": ref_id(cov["valueReference"]) if cov else None,
            "attendingPractitionerId": ref_id(atnd["individual"]) if atnd else None})
        ed = _ext(e, ED_EXT)
        if ed:
            sub = {x["url"]: x for x in ed["extension"]}
            val = lambda k: to_local(sub[k]["valueDateTime"]) if k in sub else None
            ed_rows.append({"edTrackingId": sub["trackingId"]["valueString"], "encounterId": enc_id,
                            "triageDateTime": val("triage"), "providerSeenDateTime": val("providerSeen"),
                            "roomAssignedDateTime": val("roomAssigned"), "decisionToAdmitDateTime": val("decisionToAdmit"),
                            "edDisposition": sub["disposition"]["valueString"],
                            "admittedEncounterId": sub["admittedEncounter"]["valueString"] if "admittedEncounter" in sub else None})
    return pd.DataFrame(enc_rows), pd.DataFrame(ed_rows)


def flatten_conditions(conditions: list[dict], encounters: list[dict]) -> pd.DataFrame:
    """Encounter.diagnosis.rank = 1 marks the principal diagnosis."""
    rank = {}
    enc_key = {}
    for e in encounters:
        enc_key[e["id"]] = next(i["value"] for i in e["identifier"] if i["system"].endswith("encounter-id"))
        for d in e.get("diagnosis", []):
            rank[ref_id(d["condition"])] = d.get("rank")
    rows = []
    for c in conditions:
        coding = c["code"]["coding"][0]
        rows.append({"encounterId": enc_key[ref_id(c["encounter"])], "icd10Code": coding["code"], "display": coding["display"],
                     "diagnosisRole": "principal" if rank.get(c["id"]) == 1 else "secondary"})
    return pd.DataFrame(rows)


def flatten_epic_bulk_export(folder: str | Path) -> dict[str, pd.DataFrame]:
    folder = Path(folder)
    patients = read_ndjson(folder / "Patient.ndjson")
    encounters = read_ndjson(folder / "Encounter.ndjson")
    conditions = read_ndjson(folder / "Condition.ndjson")
    pat = flatten_patients(patients)
    keys = dict(zip([p["id"] for p in patients], pat["patientId"]))
    enc, ed = flatten_encounters(encounters, keys)
    return {"patient": pat, "encounter": enc, "edTrackingEvent": ed, "condition": flatten_conditions(conditions, encounters)}
