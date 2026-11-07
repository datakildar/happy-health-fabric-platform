"""Minimal HL7v2 reader for the MEDITECH nightly batch files.

Production path: each message is converted to FHIR with Microsoft's FHIR Converter and then follows the
Epic path (notebooks/01_meditech_hl7v2_to_fhir.ipynb). This reader is the local reference mapping used by
the tests and as a fallback for the few fields the converter templates don't cover yet, such as the
assumed ZET segment that carries ED tracking events.

Times in HL7v2 usually have no UTC offset; they are read as hospital local time, which is what silver stores.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

DISPOSITION = {  # PV1-36 code -> silver text (UB-04 style codes; LWBS is a local code)
    "01": "Home", "02": "Transferred to acute", "03": "SNF", "06": "Home health", "07": "Left AMA",
    "09": "Admitted", "20": "Expired", "LWBS": "Left without being seen"}
DISPOSITION_CODE = {v: k for k, v in DISPOSITION.items()}


@dataclass
class Message:
    segments: list[list[str]]

    def all(self, seg_id: str) -> list[list[str]]:
        return [s for s in self.segments if s[0] == seg_id]

    def get(self, seg_id: str) -> list[str] | None:
        found = self.all(seg_id)
        return found[0] if found else None

    @staticmethod
    def field(seg: list[str] | None, n: int, component: int = 1) -> str | None:
        """HL7 numbering: field n (MSH counts the separator as MSH-1), component 1-based."""
        if seg is None:
            return None
        idx = n - 1 if seg[0] == "MSH" else n
        if idx >= len(seg) or seg[idx] == "":
            return None
        parts = seg[idx].split("^")
        return parts[component - 1] if component - 1 < len(parts) and parts[component - 1] != "" else None


def parse_batch(text: str) -> list[Message]:
    """Split a batch file into messages; segments may end with CR, LF or CRLF."""
    messages, current = [], []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        seg = line.split("|")
        if seg[0] == "MSH" and current:
            messages.append(Message(current))
            current = []
        current.append(seg)
    if current:
        messages.append(Message(current))
    return messages


def ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value[:12], "%Y%m%d%H%M")


def to_silver(messages: list[Message]) -> dict[str, pd.DataFrame]:
    """ADT^A03 (discharge) messages -> silver patient, encounter, condition and edTrackingEvent rows.
    When a visit appears several times in the batch, the latest message (MSH-7) wins."""
    f = Message.field
    latest: dict[str, Message] = {}
    for m in messages:
        visit = f(m.get("PV1"), 19)
        if visit and (visit not in latest or f(m.get("MSH"), 7) >= f(latest[visit].get("MSH"), 7)):
            latest[visit] = m
    pats, encs, conds, eds = {}, [], [], []
    for visit, m in latest.items():
        pid, pv1 = m.get("PID"), m.get("PV1")
        mrn = f(pid, 3)
        key = f"MEDI-{mrn}"
        birth = f(pid, 7)
        pats[key] = {"patientId": key, "sourceSystem": "MEDITECH", "localRecordNumber": mrn, "givenName": f(pid, 5, 2),
                     "familyName": f(pid, 5, 1), "birthDate": f"{birth[:4]}-{birth[4:6]}-{birth[6:8]}",
                     "gender": {"M": "male", "F": "female"}.get(f(pid, 8), "unknown"), "postalCode": f(pid, 11, 5)}
        encs.append({"encounterId": visit, "sourceSystem": "MEDITECH", "patientId": key,
                     "encounterClass": {"I": "IMP", "E": "EMER"}[f(pv1, 2)], "locationId": f(pv1, 3, 1),
                     "periodStart": ts(f(pv1, 44)), "periodEnd": ts(f(pv1, 45)),
                     "dischargeDisposition": DISPOSITION.get(f(pv1, 36)),
                     "admissionType": "elective" if f(pv1, 4) == "C" else "emergency",
                     "coverageId": f(pv1, 20), "attendingPractitionerId": f(pv1, 7, 1)})
        for dg1 in m.all("DG1"):
            conds.append({"encounterId": visit, "icd10Code": f(dg1, 3, 1), "display": f(dg1, 3, 2),
                          "diagnosisRole": "principal" if f(dg1, 15) == "1" else "secondary"})
        zet = m.get("ZET")   # assumed MEDITECH feed addition: ED tracking events
        if zet:
            eds.append({"edTrackingId": f(zet, 1), "encounterId": visit, "triageDateTime": ts(f(zet, 2)),
                        "providerSeenDateTime": ts(f(zet, 3)), "roomAssignedDateTime": ts(f(zet, 4)),
                        "decisionToAdmitDateTime": ts(f(zet, 5)), "edDisposition": f(zet, 6), "admittedEncounterId": f(zet, 7)})
    return {"patient": pd.DataFrame(pats.values()), "encounter": pd.DataFrame(encs),
            "condition": pd.DataFrame(conds), "edTrackingEvent": pd.DataFrame(eds)}


def read_meditech_folder(folder: str | Path) -> dict[str, pd.DataFrame]:
    msgs = []
    for p in sorted(Path(folder).glob("*.hl7")):
        msgs += parse_batch(p.read_text())
    return to_silver(msgs)
