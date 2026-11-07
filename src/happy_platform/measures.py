"""Reference implementation of the five quality measures (pandas).

It produces the generalized factMeasureResult rows (one per patient event x measure x run) and the
factMeasureSummary rows (one per measure x run x hospital x stratum), following the same rules as the
synthetic workbook and notebooks/05_measure_calculation.ipynb. tests/test_measures.py checks it
against the workbook results.

Simplified definitions for a demonstration dataset; the production logic follows the CMS
specification for each measure version recorded in dimMeasure.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from .identity import resolve_person
from .util import age_in_years, days_between, hours_between, minutes_between, round_half_up, to_num


@dataclass(frozen=True)
class MeasureSettings:
    """Measure parameters. In production they are versioned settings held in the MDM source."""
    readmission_window_days: int = 30
    min_age: int = 18
    sep_bundle_3h: int = 3
    sep_bundle_6h: int = 6
    lactate_repeat_threshold: float = 2
    lactate_fluids_threshold: float = 4
    fluid_ml_per_kg: int = 30


@dataclass(frozen=True)
class Run:
    run_id: str
    link_version: int
    period_start: datetime
    period_end_exclusive: datetime

    @property
    def reporting_period(self) -> str:
        return f"{self.period_start.year}-Q{(self.period_start.month + 2) // 3}"


def load_run(calc_runs: pd.DataFrame, run_id: str) -> Run:
    r = calc_runs[calc_runs["runId"] == run_id].iloc[0]
    start = pd.Timestamp(r["periodStart"]).to_pydatetime()
    end = pd.Timestamp(r["periodEnd"]).to_pydatetime() + timedelta(days=1)
    return Run(run_id, int(r["linkVersion"]), start, end)


MEASURES = {  # measureId -> (measureKey, scoringType)
    "READM-30": ("M1", "Proportion"), "SEP-1": ("M2", "Proportion"), "ED-T2P": ("M3", "Continuous variable"),
    "OP-18": ("M4", "Continuous variable"), "OP-22": ("M5", "Proportion"),
}


def _row(run: Run, measure_id: str, hospital: str, spk: str, event: str, stratum: str, in_ip: bool, in_den: bool,
         reason: str, num, obs, unit: str | None) -> dict:
    key, scoring = MEASURES[measure_id]
    return {"runId": run.run_id, "measureKey": key, "measureId": measure_id, "scoringType": scoring,
            "reportingPeriod": run.reporting_period, "hospital": hospital, "sourcePatientKey": spk, "eventKey": event,
            "stratum": stratum, "inInitialPopulation": int(in_ip), "inDenominatorOrMeasurePop": int(in_den),
            "isExclusion": int(in_ip and reason != ""), "isException": 0, "exclusionReason": reason or None,
            "inNumerator": num, "observationValue": obs, "observationUnit": unit, "expectedValue": None}


def calculate_results(t: dict[str, pd.DataFrame], run: Run, s: MeasureSettings = MeasureSettings()) -> pd.DataFrame:
    """t holds factVisit, factEdVisit, factSepsisEpisode, bridgeDiagnosis, dimPatientSource, bridgePatientLinkHistory."""
    visits, ed, seps, dx = t["factVisit"], t["factEdVisit"], t["factSepsisEpisode"], t["bridgeDiagnosis"]
    birth = dict(zip(t["dimPatientSource"]["sourcePatientKey"], t["dimPatientSource"]["birthDate"]))
    person = resolve_person(t["bridgePatientLinkHistory"], run.link_version)   # cross-site matching happens here
    in_period = lambda ts: run.period_start <= ts < run.period_end_exclusive
    hosp = lambda loc: loc[:3]
    rows: list[dict] = []

    # 1. READM-30: 30-day readmission to any Happy Health hospital, Epic or MEDITECH
    ip = visits[visits["patientClass"] == "Inpatient"]
    stays = [(person[v.sourcePatientKey], v.admitDateTime, v.plannedAdmission) for v in ip.itertuples()]
    for v in ip.itertuples():
        per, dis = person[v.sourcePatientKey], v.dischargeDateTime
        ok_period = in_period(dis)
        age = age_in_years(birth[v.sourcePatientKey], v.admitDateTime)
        reason = ("Discharged outside period" if not ok_period else "Under 18" if age < s.min_age else
                  "Died in hospital" if v.dischargeDisposition == "Expired" else
                  "Transferred to another hospital" if v.dischargeDisposition == "Transferred to acute" else
                  "Left against medical advice" if v.dischargeDisposition == "Left AMA" else "")
        in_den = ok_period and reason == ""
        nxt = min((a for p, a, planned in stays if p == per and a > dis and planned == "N"), default=None)
        days = round_half_up(days_between(dis, nxt), 1) if nxt else None
        num = int(in_den and days is not None and days <= s.readmission_window_days)
        rows.append(_row(run, "READM-30", hosp(v.locationKey), v.sourcePatientKey, v.visitKey, "All", ok_period, in_den,
                         reason, num, days, "days to readmission"))

    # 2. SEP-1: all-or-nothing bundle compliance
    vmap = visits.set_index("visitKey")
    for e in seps.itertuples():
        t0 = e.timeZero
        h = lambda x, d=2: round_half_up(hours_between(t0, x), d) if x is not None else None
        v = vmap.loc[e.visitKey]
        ok_period = in_period(t0)
        cc, to_dis = h(e.comfortCareTime), h(v["dischargeDateTime"], 1)
        reason = ("Outside period" if not ok_period else
                  "Under 18" if age_in_years(birth[e.sourcePatientKey], t0) < s.min_age else
                  "Transferred in from another hospital" if e.transferInFromAcute == "Y" else
                  "Comfort care within 6 h" if cc is not None and cc <= s.sep_bundle_6h else
                  "Discharged within 6 h" if to_dis < s.sep_bundle_6h else "")
        in_den = ok_period and reason == ""
        lact, cult, abx = h(e.initialLactateTime), h(e.bloodCultureTime), h(e.antibioticStartTime)
        initial = to_num(e.initialLactateValue)
        repeat_needed = initial > s.lactate_repeat_threshold
        fluids_needed = e.severity == "Septic shock" or initial >= s.lactate_fluids_threshold
        given, fluid_h = to_num(e.crystalloidVolumeMl) or 0, h(e.crystalloidStartTime)
        vaso_needed, vaso_h = e.persistentHypotension == "Y", h(e.vasopressorStartTime)
        elements = [
            lact is not None and lact <= s.sep_bundle_3h,                                        # initial lactate
            cult is not None and abx is not None and cult <= abx and cult <= s.sep_bundle_3h,    # cultures before antibiotics
            abx is not None and abx <= s.sep_bundle_3h,                                          # antibiotics
            (not repeat_needed) or (h(e.repeatLactateTime) is not None and h(e.repeatLactateTime) <= s.sep_bundle_6h),
            (not fluids_needed) or (given >= to_num(e.weightKg) * s.fluid_ml_per_kg and fluid_h is not None and fluid_h <= s.sep_bundle_3h),
            (not vaso_needed) or (vaso_h is not None and vaso_h <= s.sep_bundle_6h),
        ]
        rows.append(_row(run, "SEP-1", hosp(v["locationKey"]), e.sourcePatientKey, e.episodeKey, "All", ok_period, in_den,
                         reason, int(in_den and all(elements)), None, None))

    # 3. ED-T2P: median minutes from arrival to provider (internal, former OP-20)
    for e in ed.itertuples():
        ok_period = in_period(e.arrivalDateTime)
        reason = "Outside period" if not ok_period else ("Left without being seen" if e.providerSeenDateTime is None else "")
        in_den = ok_period and reason == ""
        obs = round_half_up(minutes_between(e.arrivalDateTime, e.providerSeenDateTime)) if in_den else None
        rows.append(_row(run, "ED-T2P", hosp(e.locationKey), e.sourcePatientKey, e.edVisitKey, "All", ok_period, in_den,
                         reason, None, obs, "minutes"))

    # 4. OP-18: median minutes from arrival to departure, discharged patients, two strata
    mental = set(dx.loc[dx["isMentalHealth"].astype(int) > 0, "visitKey"])
    for e in ed.itertuples():
        ok_period = in_period(e.arrivalDateTime)
        reason = "Outside period" if not ok_period else ("" if e.edDisposition == "Discharged" else f"Not discharged ({e.edDisposition})")
        in_pop = ok_period and reason == ""
        stratum = "Mental health (OP-18c)" if e.visitKey in mental else "Main (OP-18b)"
        obs = round_half_up(minutes_between(e.arrivalDateTime, e.departureDateTime)) if in_pop else None
        rows.append(_row(run, "OP-18", hosp(e.locationKey), e.sourcePatientKey, e.edVisitKey, stratum, ok_period, in_pop,
                         reason, None, obs, "minutes"))

    # 5. OP-22: share of ED visits that left without being seen (lower is better)
    for e in ed.itertuples():
        ok_period = in_period(e.arrivalDateTime)
        rows.append(_row(run, "OP-22", hosp(e.locationKey), e.sourcePatientKey, e.edVisitKey, "All", ok_period, ok_period,
                         "" if ok_period else "Outside period", int(ok_period and e.edDisposition == "LWBS"), None, None))

    out = pd.DataFrame(rows)
    out.insert(0, "resultKey", [f"MR-{i:04d}" for i in range(1, len(out) + 1)])
    return out


def summarize(results: pd.DataFrame, hospitals: list[str]) -> pd.DataFrame:
    """factMeasureSummary: one row per measure x hospital (plus ALL) x stratum; the scoring type picks rate or median."""
    specs = [("READM-30", "All"), ("SEP-1", "All"), ("ED-T2P", "All"), ("OP-18", "Main (OP-18b)"), ("OP-22", "All")]
    out = []
    for mid, stratum in specs:
        cells = [(h, stratum) for h in ["ALL"] + hospitals]
        if mid == "OP-18":
            cells.append(("ALL", "Mental health (OP-18c)"))
        for h, st in cells:
            r = results[results["measureId"] == mid]
            if h != "ALL":
                r = r[r["hospital"] == h]
            if st != "All":
                r = r[r["stratum"] == st]
            key, scoring = MEASURES[mid]
            den = int(r["inDenominatorOrMeasurePop"].sum())
            num = int(r.loc[r["inDenominatorOrMeasurePop"] == 1, "inNumerator"].fillna(0).sum()) if scoring == "Proportion" else None
            obs = [v for v in r.loc[r["inDenominatorOrMeasurePop"] == 1, "observationValue"] if v is not None and not pd.isna(v)]
            median = statistics.median(obs) if scoring == "Continuous variable" and obs else None
            value = (num / den if den else None) if scoring == "Proportion" else median
            out.append({"runId": r["runId"].iloc[0] if len(r) else results["runId"].iloc[0], "measureKey": key, "measureId": mid,
                        "scoringType": scoring, "hospital": h, "stratum": st,
                        "initialPopulation": int(r["inInitialPopulation"].sum()), "exclusions": int(r["isExclusion"].sum()),
                        "denominatorOrMeasurePop": den, "numerator": num, "observationMedian": median, "resultValue": value})
    df = pd.DataFrame(out)
    df.insert(0, "summaryKey", [f"MS-{i:03d}" for i in range(1, len(df) + 1)])
    return df
