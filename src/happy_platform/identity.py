"""Versioned patient links: resolve a link version, and publish a new one.

Rules (docs/patient-matching.md):
* A link version is a release number for the whole identity state. It goes up by one only when
  a matching run publishes at least one change; a run with no change creates no version.
* bridgePatientLinkHistory rows are never updated in place except to close them: the old row gets
  versionTo = N - 1 and a new row is added with versionFrom = N, versionTo = 999 (open).
* A calculation run pins the version it used; resolving that version always returns exactly one
  row per source record.
* The control table (linkVersion) row is flipped to 'published' last. Readers only use versions
  up to the latest published one, so a half-built version is invisible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

OPEN = 999


def links_as_of(links: pd.DataFrame, version: int) -> pd.DataFrame:
    """Rows of bridgePatientLinkHistory in force for one link version (versionFrom <= v <= versionTo)."""
    vf = links["versionFrom"].astype(int)
    vt = links["versionTo"].astype(int)
    out = links[(vf <= version) & (version <= vt)]
    dupes = out["sourcePatientKey"][out["sourcePatientKey"].duplicated()]
    if len(dupes):
        raise ValueError(f"link version {version}: more than one row for {sorted(set(dupes))}")
    return out


def resolve_person(links: pd.DataFrame, version: int) -> dict[str, str]:
    """sourcePatientKey -> personId for the given link version."""
    cur = links_as_of(links, version)
    return dict(zip(cur["sourcePatientKey"], cur["personId"]))


def latest_published(control: pd.DataFrame) -> int:
    pub = control[control["status"] == "published"]
    return int(pub["linkVersion"].astype(int).max())


@dataclass
class PublishResult:
    version: int | None
    links: pd.DataFrame
    persons: pd.DataFrame
    control: pd.DataFrame
    changed: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


def publish_link_version(
    links: pd.DataFrame,
    persons: pd.DataFrame,
    control: pd.DataFrame,
    proposed: dict[str, dict],
    matching_run_id: str,
    mdm_settings_version: str,
    published_at: datetime,
) -> PublishResult:
    """Apply a matching run's proposed links.

    proposed: sourcePatientKey -> {"personId", "validFrom", "linkMethod", "matchProbability"} for every record
    whose link the run proposes (records not listed keep their current link).
    """
    latest = latest_published(control)
    current = resolve_person(links, latest)
    changed = [k for k, p in proposed.items() if current.get(k) != p["personId"]]
    if not changed:
        return PublishResult(None, links, persons, control)

    n = latest + 1
    links = links.copy()
    persons = persons.copy()
    next_link = int(links["linkId"].str[2:].astype(int).max()) + 1
    new_rows = []
    for k in changed:
        open_idx = links.index[(links["sourcePatientKey"] == k) & (links["versionTo"].astype(int) == OPEN)]
        links.loc[open_idx, "versionTo"] = n - 1                      # close the old row
        p = proposed[k]
        new_rows.append({"linkId": f"LK{next_link:03d}", "sourcePatientKey": k, "personNum": int(p["personId"][2:]),
                         "personId": p["personId"], "versionFrom": n, "versionTo": OPEN, "validFrom": p["validFrom"],
                         "recordedAt": published_at, "linkMethod": p["linkMethod"], "matchProbability": p["matchProbability"],
                         "mdmSettingsVersion": mdm_settings_version})
        next_link += 1
    links = pd.concat([links, pd.DataFrame(new_rows)], ignore_index=True)

    # people created or left without records
    after = resolve_person(links, n)
    known = set(persons["personId"])
    created = sorted({p for p in after.values() if p not in known})
    for pid in created:
        persons.loc[len(persons)] = {"personId": pid, "personNum": int(pid[2:]), "status": "Active", "forwardedTo": None,
                                     "note": f"Created in link version {n}"}
    with_records = set(after.values())
    retired = []
    for i, row in persons.iterrows():
        if row["status"] == "Active" and row["personId"] not in with_records:
            moved_to = {after[k] for k, old in current.items() if old == row["personId"]}
            persons.loc[i, ["status", "forwardedTo", "note"]] = ["Retired", next(iter(moved_to)) if len(moved_to) == 1 else None,
                                                                 f"Retired in link version {n}"]
            retired.append(row["personId"])

    validate_links(links, persons, n)
    control = pd.concat([control, pd.DataFrame([{
        "linkVersion": n, "status": "published", "publishedAt": published_at, "matchingRunId": matching_run_id,
        "mdmSettingsVersion": mdm_settings_version, "linksChanged": len(changed), "personsCreated": len(created),
        "personsRetired": len(retired)}])], ignore_index=True)
    return PublishResult(n, links, persons, control, changed, created, retired)


def assign_person_ids(clusters: dict[str, str], links: pd.DataFrame, persons: pd.DataFrame, version: int) -> dict[str, str]:
    """Turn matching clusters (sourcePatientKey -> clusterId) into person IDs, keeping IDs as stable as possible.

    * A cluster whose records all belong to one current person keeps that person.
    * A cluster joining records of several current persons keeps the oldest person (lowest number);
      the others are retired by publish_link_version with a forwarding pointer.
    * When one person's records end up in several clusters (a split), the person stays with the largest
      cluster, then with the cluster holding the record that was linked to it first; the other clusters
      get new person IDs.
    * A cluster of only new records gets a new person ID.
    """
    cur = links_as_of(links, version).set_index("sourcePatientKey")
    first_link = cur["linkId"].to_dict()
    members: dict[str, list[str]] = {}
    for k, c in clusters.items():
        members.setdefault(c, []).append(k)
    next_num = int(persons["personNum"].astype(int).max()) + 1
    claimed: dict[str, str] = {}                               # personId -> clusterId that keeps it
    # rank clusters so the biggest / earliest-linked claims an existing person first
    order = sorted(members, key=lambda c: (-len(members[c]), min(first_link.get(k, "LZZZ") for k in members[c])))
    assigned: dict[str, str] = {}
    for c in order:
        current = sorted({cur.loc[k, "personId"] for k in members[c] if k in cur.index}, key=lambda p: int(p[2:]))
        keep = next((p for p in current if p not in claimed), None)
        if keep is None:
            keep = f"P-{next_num:04d}"
            next_num += 1
        claimed[keep] = c
        for k in members[c]:
            assigned[k] = keep
    return assigned


def validate_links(links: pd.DataFrame, persons: pd.DataFrame, version: int) -> None:
    """Checks run before the control row is flipped to 'published'."""
    cur = links_as_of(links, version)                         # raises if a record has two rows
    open_rows = links[links["versionTo"].astype(int) == OPEN]
    if open_rows["sourcePatientKey"].duplicated().any():
        raise ValueError("a source record has more than one open link row")
    active = set(persons.loc[persons["status"] == "Active", "personId"])
    empty = active - set(cur["personId"])
    if empty:
        raise ValueError(f"active persons with no source records: {sorted(empty)}")
    unknown = set(cur["personId"]) - set(persons["personId"])
    if unknown:
        raise ValueError(f"links point to unknown persons: {sorted(unknown)}")
