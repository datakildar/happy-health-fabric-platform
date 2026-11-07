"""Load the sample layers into pandas with the right types."""
from __future__ import annotations

import pandas as pd

from pathlib import Path

from .util import SAMPLES, read_csv

DT = ("admitDateTime", "dischargeDateTime", "arrivalDateTime", "triageDateTime", "providerSeenDateTime", "roomAssignedDateTime",
      "decisionToAdmitDateTime", "departureDateTime", "timeZero", "initialLactateTime", "bloodCultureTime", "antibioticStartTime",
      "repeatLactateTime", "crystalloidStartTime", "vasopressorStartTime", "comfortCareTime", "periodStart", "periodEnd",
      "recordedAt", "runDateTime", "publishedAt")
DATES = ("birthDate", "validFrom", "effectiveFrom", "effectiveTo")


def load_gold(root: str | Path = SAMPLES) -> dict[str, pd.DataFrame]:
    """Gold star schema tables plus the shared identity tables (read through a shortcut in Fabric).
    root: the samples folder (default: this repository's samples/; in Fabric e.g. /lakehouse/default/Files/samples)."""
    root = Path(root)
    names = ["factVisit", "factEdVisit", "factSepsisEpisode", "bridgeDiagnosis", "dimCalculationRun", "dimMeasure",
             "dimLocation", "factMeasureResult", "factMeasureSummary"]
    t = {n: read_csv(root / "gold" / f"{n}.csv", DT, DATES) for n in names}
    t.update(load_identity(root))
    return t


def load_identity(root: str | Path = SAMPLES) -> dict[str, pd.DataFrame]:
    root = Path(root)
    names = ["dimPatientSource", "dimPerson", "bridgePatientLinkHistory", "linkVersion"]
    return {n: read_csv(root / "silver" / "identity" / f"{n}.csv", DT, DATES) for n in names}


def load_silver_clinical(root: str | Path = SAMPLES) -> dict[str, pd.DataFrame]:
    root = Path(root)
    names = ["patient", "encounter", "edTrackingEvent", "condition", "sepsisEpisode"]
    return {n: read_csv(root / "silver" / "clinical" / f"{n}.csv", DT, DATES) for n in names}


def hospitals(dim_location: pd.DataFrame) -> list[str]:
    return sorted({k[:3] for k in dim_location["locationKey"]})
