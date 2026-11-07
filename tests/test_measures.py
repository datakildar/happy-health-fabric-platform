"""The reference measure implementation must reproduce the synthetic workbook exactly."""
import json
import math

import pandas as pd
import pytest

from happy_platform.measures import calculate_results, load_run, summarize
from happy_platform.samples import hospitals, load_gold
from happy_platform.util import SAMPLES


@pytest.fixture(scope="module")
def gold():
    return load_gold()


def run_all(gold, run_id):
    run = load_run(gold["dimCalculationRun"], run_id)
    res = calculate_results(gold, run)
    return res, summarize(res, hospitals(gold["dimLocation"]))


def close(a, b):
    if a in (None, "") or (isinstance(a, float) and math.isnan(a)):
        return b in (None, "") or (isinstance(b, float) and math.isnan(b))
    return math.isclose(float(a), float(b), rel_tol=1e-9)


def test_headline_results_run_01(gold):
    _, s = run_all(gold, "R-2026Q3-01")
    got = {(r.measureId, r.stratum): r.resultValue for r in s[s.hospital == "ALL"].itertuples()}
    assert got[("READM-30", "All")] == pytest.approx(6 / 42)
    assert got[("SEP-1", "All")] == pytest.approx(0.5)
    assert got[("ED-T2P", "All")] == 46.5
    assert got[("OP-18", "Main (OP-18b)")] == 207
    assert got[("OP-18", "Mental health (OP-18c)")] == 127.5
    assert got[("OP-22", "All")] == pytest.approx(3 / 41)


def test_every_summary_row_matches_workbook(gold):
    """All 91 factMeasureSummary rows (measure x hospital x stratum), counts and results."""
    _, s = run_all(gold, "R-2026Q3-01")
    expected = json.load(open(SAMPLES / "reference" / "expected_results.json"))["byHospital"]
    assert len(expected) == len(s)
    got = {(r.measureId, r.hospital, r.stratum): r for r in s.itertuples()}
    for e in expected:
        r = got[(e["measureId"], e["hospital"], e["stratum"])]
        for f in ("initialPopulation", "exclusions", "denominatorOrMeasurePop", "numerator", "observationMedian", "resultValue"):
            assert close(e[f], getattr(r, f)), (e["measureId"], e["hospital"], f, e[f], getattr(r, f))


def test_patient_level_rows_match_workbook(gold):
    """Every factMeasureResult row: population flags, exclusion reason, numerator and observation."""
    res, _ = run_all(gold, "R-2026Q3-01")
    wb = gold["factMeasureResult"]
    assert len(res) == len(wb) == 193
    mine = res.set_index(["measureId", "eventKey"])
    for r in wb.itertuples():
        m = mine.loc[(r.measureId, r.eventKey)]
        assert m["hospital"] == r.hospital and m["sourcePatientKey"] == r.sourcePatientKey and m["stratum"] == r.stratum
        for f in ("inInitialPopulation", "inDenominatorOrMeasurePop", "isExclusion", "inNumerator", "observationValue"):
            assert close(getattr(r, f), m[f]), (r.measureId, r.eventKey, f, getattr(r, f), m[f])
        blank = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) or v == "" else v
        assert blank(r.exclusionReason) == blank(m["exclusionReason"]), (r.measureId, r.eventKey)


def test_run_02_uses_link_version_8(gold):
    """After the split in link version 8, one readmission is no longer cross-site: 5 / 42 = 11.9%."""
    _, s = run_all(gold, "R-2026Q3-02")
    r = s[(s.measureId == "READM-30") & (s.hospital == "ALL")].iloc[0]
    assert (r.numerator, r.denominatorOrMeasurePop) == (5, 42)
    assert round(r.resultValue, 3) == 0.119


def test_numerator_is_subset_of_denominator(gold):
    res, _ = run_all(gold, "R-2026Q3-01")
    prop = res[res.scoringType == "Proportion"]
    assert not ((prop.inNumerator == 1) & (prop.inDenominatorOrMeasurePop == 0)).any()
