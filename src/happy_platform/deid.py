"""HIPAA Safe Harbor rules for structured fields in the research extract.

Free text goes through Presidio in notebooks/06_research_deidentification.ipynb; these deterministic
rules cover the structured columns and are unit-tested. The privacy officer signs off each release.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime

import pandas as pd

from .util import age_in_years

# Three-digit ZIP prefixes whose combined population is 20,000 or fewer must be released as 000.
# List from HHS de-identification guidance (Census 2000); refresh it against current Census data before each release.
RESTRICTED_ZIP3 = {"036", "059", "063", "102", "203", "556", "692", "790", "821", "823", "830", "831", "878", "879", "884", "890", "893"}

DIRECT_IDENTIFIERS = {"givenName", "familyName", "firstName", "lastName", "localRecordNumber", "phone", "email", "address",
                      "street", "ssn", "medicareBeneficiaryId", "nationalProviderId", "sourcePatientKey", "patientId"}


def year_only(value: date | datetime | None) -> int | None:
    """All date elements except the year are removed."""
    return value.year if value is not None else None


def safe_age(birth: date, on: date | datetime) -> str:
    """Ages over 89 are grouped into a single category of 90 or older."""
    age = age_in_years(birth, on)
    return "90+" if age > 89 else str(age)


def zip3(zip_code: str | None) -> str | None:
    if not zip_code:
        return None
    z = str(zip_code)[:3]
    return "000" if z in RESTRICTED_ZIP3 else z


def new_study_ids(keys: list[str]) -> dict[str, str]:
    """Random study IDs. Not derived from any identifier; the crosswalk stays inside Happy Health and is never released."""
    ids, used = {}, set()
    for k in keys:
        while True:
            sid = "S-" + secrets.token_hex(5).upper()
            if sid not in used:
                used.add(sid)
                ids[k] = sid
                break
    return ids


def deidentify_visits(visits: pd.DataFrame, patients: pd.DataFrame, person_of: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per visit, keyed by a random study ID per person. Returns (extract, crosswalk)."""
    pmap = patients.set_index("sourcePatientKey")
    persons = sorted({person_of[k] for k in visits["sourcePatientKey"]})
    sid = new_study_ids(persons)
    rows = []
    for v in visits.itertuples():
        p = pmap.loc[v.sourcePatientKey]
        rows.append({"studyId": sid[person_of[v.sourcePatientKey]], "admitYear": year_only(v.admitDateTime),
                     "ageAtAdmit": safe_age(p["birthDate"], v.admitDateTime), "sex": p["sex"], "zip3": zip3(p["zip"]),
                     "patientClass": v.patientClass, "lengthOfStayDays": (v.dischargeDateTime - v.admitDateTime).days,
                     "dischargeDisposition": v.dischargeDisposition, "principalDxCode": v.principalDxCode})
    crosswalk = pd.DataFrame({"personId": list(sid), "studyId": list(sid.values())})
    return pd.DataFrame(rows), crosswalk


def check_release(extract: pd.DataFrame) -> list[str]:
    """Automated release checks; any failure blocks the release."""
    problems = []
    leaked = DIRECT_IDENTIFIERS & set(extract.columns)
    if leaked:
        problems.append(f"direct identifier columns present: {sorted(leaked)}")
    for c in extract.columns:
        if extract[c].map(lambda x: isinstance(x, (date, datetime))).any():
            problems.append(f"column {c} holds full dates; only years are allowed")
    if "zip3" in extract.columns and extract["zip3"].dropna().isin(RESTRICTED_ZIP3).any():
        problems.append("restricted three-digit ZIP released")
    if "ageAtAdmit" in extract.columns and extract["ageAtAdmit"].map(lambda a: a != "90+" and a is not None and int(a) > 89).any():
        problems.append("age over 89 not grouped")
    return problems
