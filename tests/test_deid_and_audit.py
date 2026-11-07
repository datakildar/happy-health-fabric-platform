from datetime import date, datetime

import pytest

from happy_platform.audit import MemoryWriter, RunLogger
from happy_platform.deid import check_release, deidentify_visits, safe_age, zip3
from happy_platform.identity import resolve_person
from happy_platform.samples import load_gold


def test_safe_harbor_rules():
    assert zip3("33341") == "333"
    assert zip3("03601") == "000"                 # restricted three-digit ZIP
    assert safe_age(date(1930, 1, 1), date(2026, 7, 1)) == "90+"
    assert safe_age(date(1961, 1, 24), date(2026, 7, 2)) == "65"


def test_research_extract_passes_release_checks():
    g = load_gold()
    person = resolve_person(g["bridgePatientLinkHistory"], 8)
    extract, crosswalk = deidentify_visits(g["factVisit"], g["dimPatientSource"], person)
    assert check_release(extract) == []
    assert extract["studyId"].nunique() == crosswalk["studyId"].nunique()
    assert not set(crosswalk["studyId"]) & set(person.values())


def test_release_check_blocks_identifiers():
    g = load_gold()
    bad = g["factVisit"][["sourcePatientKey", "admitDateTime"]]
    problems = check_release(bad)
    assert any("direct identifier" in p for p in problems) and any("full dates" in p for p in problems)


def test_run_logger_records_errors():
    w = MemoryWriter()
    log = RunLogger("05_measure_calculation", writer=w, calcRunId="R-2026Q3-01", linkVersion=7)
    with pytest.raises(ZeroDivisionError):
        with log.step("calculate"):
            1 / 0
    assert w.tables["notebookErrorLog"][0]["errorType"] == "ZeroDivisionError"
    assert w.tables["notebookRunLog"][0]["status"] == "Failed" and w.tables["notebookRunLog"][0]["linkVersion"] == 7
