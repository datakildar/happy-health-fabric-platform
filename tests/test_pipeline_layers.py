"""Bronze -> silver -> gold: the sample layers agree with each other."""
import pandas as pd
import pytest

from happy_platform.fhir_flatten import flatten_epic_bulk_export
from happy_platform.gold_build import build_gold
from happy_platform.hl7v2 import read_meditech_folder
from happy_platform.samples import load_gold, load_silver_clinical
from happy_platform.util import SAMPLES


def norm(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        out[c] = out[c].map(lambda v: "" if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)) else
                            (v.isoformat(timespec="minutes") if hasattr(v, "hour") else (v.isoformat() if hasattr(v, "isoformat") else str(v))))
    return out.sort_values(keys).reset_index(drop=True)


@pytest.fixture(scope="module")
def silver():
    return load_silver_clinical()


@pytest.fixture(scope="module")
def bronze_flattened():
    epic = flatten_epic_bulk_export(SAMPLES / "bronze" / "epic_fhir")
    meditech = read_meditech_folder(SAMPLES / "bronze" / "meditech_hl7v2")
    return {k: pd.concat([epic[k], meditech[k]], ignore_index=True) for k in epic}


@pytest.mark.parametrize("table,keys", [("patient", ["patientId"]), ("encounter", ["encounterId"]),
                                        ("edTrackingEvent", ["edTrackingId"]), ("condition", ["encounterId", "icd10Code"])])
def test_bronze_flattens_to_silver(silver, bronze_flattened, table, keys):
    exp = norm(silver[table], keys)
    got = norm(bronze_flattened[table][silver[table].columns], keys)
    pd.testing.assert_frame_equal(got, exp)


@pytest.mark.parametrize("table,keys", [("factVisit", ["visitKey"]), ("factEdVisit", ["edVisitKey"]),
                                        ("bridgeDiagnosis", ["visitKey", "dxCode"]), ("factSepsisEpisode", ["episodeKey"])])
def test_silver_builds_gold(silver, table, keys):
    gold = load_gold()
    built = build_gold(silver)[table]
    exp = norm(gold[table], keys)
    got = norm(built[gold[table].columns], keys)
    pd.testing.assert_frame_equal(got, exp)
