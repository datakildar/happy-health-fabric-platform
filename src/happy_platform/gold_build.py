"""Silver (FHIR-shaped) -> gold star schema, reference implementation (pandas).

Mirrors notebooks/04_silver_to_gold_star_schema.ipynb. Facts keep the source patient key, never the
person ID: which person a record belongs to can change, the record cannot.
"""
from __future__ import annotations

import pandas as pd

CLASS = {"IMP": "Inpatient", "EMER": "Emergency"}


def build_fact_visit(encounter: pd.DataFrame, condition: pd.DataFrame) -> pd.DataFrame:
    principal = condition[condition["diagnosisRole"] == "principal"].drop_duplicates("encounterId")
    df = encounter.merge(principal[["encounterId", "icd10Code"]], on="encounterId", how="left")
    return pd.DataFrame({
        "visitKey": df["encounterId"], "sourcePatientKey": df["patientId"], "locationKey": df["locationId"],
        "sourceSystem": df["sourceSystem"], "patientClass": df["encounterClass"].map(CLASS),
        "admitDateTime": df["periodStart"], "dischargeDateTime": df["periodEnd"], "dischargeDisposition": df["dischargeDisposition"],
        "plannedAdmission": (df["admissionType"] == "elective").map({True: "Y", False: "N"}), "payerKey": df["coverageId"],
        "attendingPractitionerKey": df["attendingPractitionerId"], "principalDxCode": df["icd10Code"]})


def build_fact_ed_visit(ed: pd.DataFrame, encounter: pd.DataFrame) -> pd.DataFrame:
    df = ed.merge(encounter, on="encounterId", how="inner")
    return pd.DataFrame({
        "edVisitKey": df["edTrackingId"], "visitKey": df["encounterId"], "sourcePatientKey": df["patientId"],
        "locationKey": df["locationId"], "arrivalDateTime": df["periodStart"], "triageDateTime": df["triageDateTime"],
        "providerSeenDateTime": df["providerSeenDateTime"], "roomAssignedDateTime": df["roomAssignedDateTime"],
        "decisionToAdmitDateTime": df["decisionToAdmitDateTime"], "departureDateTime": df["periodEnd"],
        "edDisposition": df["edDisposition"], "admittedVisitKey": df["admittedEncounterId"]})


def build_bridge_diagnosis(condition: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "visitKey": condition["encounterId"], "dxCode": condition["icd10Code"], "dxDescription": condition["display"],
        "dxType": condition["diagnosisRole"].map({"principal": "Principal", "secondary": "Secondary"}),
        # simplified mental-health flag for the OP-18c stratum: ICD-10-CM chapter F
        "isMentalHealth": condition["icd10Code"].str.startswith("F").astype(int)})


def build_fact_sepsis_episode(sepsis: pd.DataFrame, encounter: pd.DataFrame) -> pd.DataFrame:
    df = sepsis.merge(encounter[["encounterId", "patientId"]], on="encounterId", how="left")
    df = df.rename(columns={"sepsisEpisodeId": "episodeKey", "encounterId": "visitKey", "patientId": "sourcePatientKey"})
    cols = ["episodeKey", "visitKey", "sourcePatientKey"] + [c for c in sepsis.columns if c not in ("sepsisEpisodeId", "encounterId")]
    return df[cols]


def build_gold(silver: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    enc, cond = silver["encounter"], silver["condition"]
    return {"factVisit": build_fact_visit(enc, cond), "factEdVisit": build_fact_ed_visit(silver["edTrackingEvent"], enc),
            "bridgeDiagnosis": build_bridge_diagnosis(cond), "factSepsisEpisode": build_fact_sepsis_episode(silver["sepsisEpisode"], enc)}
