"""Link versions: exactly one row per record per version, and publishing reproduces versions 7 and 8."""
from datetime import date, datetime

import pandas as pd
import pytest

from happy_platform.identity import OPEN, links_as_of, publish_link_version, resolve_person
from happy_platform.samples import load_identity


@pytest.fixture()
def ident():
    return load_identity()


def test_one_row_per_record_in_every_version(ident):
    links = ident["bridgePatientLinkHistory"]
    for v in range(1, 9):
        cur = links_as_of(links, v)
        assert cur["sourcePatientKey"].is_unique
        assert len(cur) == 43


def test_sample_versions(ident):
    links = ident["bridgePatientLinkHistory"]
    assert resolve_person(links, 6)["MEDI-88005"] == "P-0041"
    assert resolve_person(links, 7)["MEDI-88005"] == "P-0005"
    assert resolve_person(links, 7)["MEDI-88012"] == "P-0012"
    assert resolve_person(links, 8)["MEDI-88012"] == "P-0042"


def state_as_of(ident, version):
    """Rebuild the identity tables as they were when `version` was the latest published version."""
    links = ident["bridgePatientLinkHistory"].copy()
    links = links[links["versionFrom"].astype(int) <= version].copy()
    links.loc[links["versionTo"].astype(int) >= version, "versionTo"] = OPEN
    persons = ident["dimPerson"].copy()
    live = set(links_as_of(links, version)["personId"])
    persons = persons[persons["personId"].isin(live | set(persons.loc[persons["status"] == "Retired", "personId"]) - {"P-0042"})].copy()
    persons.loc[persons["personId"].isin(live), ["status", "forwardedTo", "note"]] = ["Active", None, "Created at first load"]
    control = ident["linkVersion"]
    control = control[control["linkVersion"].astype(int) <= version].copy()
    return links, persons, control


def test_publish_version_7_match(ident):
    links, persons, control = state_as_of(ident, 6)
    r = publish_link_version(links, persons, control,
                             {"MEDI-88005": {"personId": "P-0005", "validFrom": date(2026, 7, 28), "linkMethod": "Steward", "matchProbability": 0.81}},
                             "MR-20260929", "MDM-2", datetime(2026, 9, 30, 3, 0))
    assert r.version == 7 and r.changed == ["MEDI-88005"] and r.retired == ["P-0041"]
    assert resolve_person(r.links, 7)["MEDI-88005"] == "P-0005"
    assert resolve_person(r.links, 6)["MEDI-88005"] == "P-0041"          # history is kept
    retired = r.persons.set_index("personId").loc["P-0041"]
    assert retired["status"] == "Retired" and retired["forwardedTo"] == "P-0005"


def test_publish_version_8_split(ident):
    links, persons, control = state_as_of(ident, 7)
    r = publish_link_version(links, persons, control,
                             {"MEDI-88012": {"personId": "P-0042", "validFrom": date(2026, 8, 20), "linkMethod": "Steward (split)", "matchProbability": 0.0}},
                             "MR-20261014", "MDM-3", datetime(2026, 10, 15, 3, 0))
    assert r.version == 8 and r.created == ["P-0042"]
    expected = resolve_person(ident["bridgePatientLinkHistory"], 8)
    assert resolve_person(r.links, 8) == expected                         # same state as the sample data
    assert resolve_person(r.links, 7)["MEDI-88012"] == "P-0012"           # run R-2026Q3-01 still sees version 7


def test_no_change_creates_no_version(ident):
    links, persons, control = state_as_of(ident, 8)
    r = publish_link_version(links, persons, control,
                             {"MEDI-88015": {"personId": "P-0015", "validFrom": date(2026, 5, 1), "linkMethod": "Exact", "matchProbability": 1}},
                             "MR-20261101", "MDM-3", datetime(2026, 11, 1, 3, 0))
    assert r.version is None and len(r.control) == len(control)


def test_assign_person_ids_merge_and_split(ident):
    from happy_platform.identity import assign_person_ids
    links, persons = ident["bridgePatientLinkHistory"], ident["dimPerson"]
    # version 6 -> 7: matching puts EPIC-10005 and MEDI-88005 in one cluster
    clusters = dict(resolve_person(links, 6))                          # cluster = current person
    clusters["MEDI-88005"] = clusters["EPIC-10005"]
    got = assign_person_ids(clusters, links, persons, 6)
    assert got["MEDI-88005"] == got["EPIC-10005"] == "P-0005"          # oldest person survives
    # version 7 -> 8: the steward splits MEDI-88012 from EPIC-10012
    clusters = dict(resolve_person(links, 7))
    clusters["MEDI-88012"] = "split-off"
    got = assign_person_ids(clusters, links, persons[persons.personId != "P-0042"], 7)  # before P-0042 existed
    assert got["EPIC-10012"] == "P-0012" and got["MEDI-88012"] == "P-0042"
    assert all(got[k] == p for k, p in resolve_person(links, 7).items() if k not in ("MEDI-88012",))
