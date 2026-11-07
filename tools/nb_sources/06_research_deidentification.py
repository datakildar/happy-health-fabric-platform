# %% [markdown]
# # 06 – De-identified research extract (HIPAA Safe Harbor)
#
# **Release flow**
# 1. Start from an approved column list for the study; nothing else is read.
# 2. Structured fields: dates → year, ages over 89 → "90+", ZIP → first three digits (000 for small areas), direct identifiers dropped (`happy_platform.deid`).
# 3. Free text: Presidio finds and replaces names, dates, phone numbers, addresses and record numbers.
# 4. Random study IDs per person; the crosswalk stays in Happy Health's restricted lakehouse and is never released.
# 5. Automated release checks; any failure blocks the release.
# 6. A release report (row counts, check results, lineage, tool versions) goes to the privacy officer, who signs before the extract is written to `lh_research`.
#
# Exact dates for a study need Expert Determination or a limited data set under a data use agreement instead of Safe Harbor.

# %% tags=["parameters"]
USE_SAMPLES = True
SAMPLES_PATH = "../samples"                       # in Fabric: /lakehouse/default/Files/samples
GOLD = "lh_gold_quality"
IDENTITY = "lh_silver_identity"
RESEARCH = "lh_research"
RESTRICTED = "lh_restricted"           # holds the study ID crosswalk
STUDY_ID = "NGO-2026-014"
APPROVED_COLUMNS = ["admitYear", "ageAtAdmit", "sex", "zip3", "patientClass", "lengthOfStayDays", "dischargeDisposition", "principalDxCode", "noteText"]
PIPELINE_RUN_ID = ""

# %%
import json
from datetime import datetime, timezone

import pandas as pd

from happy_platform.audit import RunLogger
from happy_platform.deid import check_release, deidentify_visits
from happy_platform.identity import latest_published, resolve_person

log = RunLogger("06_research_deidentification", studyId=STUDY_ID, pipelineRunId=PIPELINE_RUN_ID)
if USE_SAMPLES:
    from happy_platform.samples import load_gold
    g = load_gold(SAMPLES_PATH)
    visits, patients, links, control = g["factVisit"], g["dimPatientSource"], g["bridgePatientLinkHistory"], g["linkVersion"]
else:
    visits = spark.table(f"{GOLD}.factVisit").toPandas()
    patients = spark.table(f"{IDENTITY}.dimPatientSource").toPandas()
    links = spark.table(f"{IDENTITY}.bridgePatientLinkHistory").toPandas()
    control = spark.table(f"{IDENTITY}.linkVersion").toPandas()

version = latest_published(control)
extract, crosswalk = deidentify_visits(visits, patients, resolve_person(links, version))
print(f"{len(extract)} visits, {extract['studyId'].nunique()} study participants (link version {version})")
extract.head()

# %% [markdown]
# ## Free text with Presidio
# Illustrative discharge notes; in production the note text comes from the clinical notes tables and only for studies whose approval covers notes.

# %%
notes = pd.DataFrame({"visitKey": visits["visitKey"].head(3), "noteText": [
    "Mr. John Jones, MRN 10005, seen 07/06/2026 at Happy Health North. Call daughter at 305-555-0142.",
    "Patient Mary Johnson discharged home on 07/23/2026; follow up with Dr. White in 2 weeks.",
    "Readmitted from Riverside Hospital, 1200 River Rd, Miami FL 33141. Lactate 2.6."]})

try:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    analyzer = AnalyzerEngine()          # needs a spaCy English model in the Fabric environment
    analyzer.registry.add_recognizer(PatternRecognizer(supported_entity="MRN", patterns=[Pattern("mrn", r"\bMRN\s*\d{4,10}\b", 0.85)]))
    anonymizer = AnonymizerEngine()
    ENTITIES = ["PERSON", "DATE_TIME", "PHONE_NUMBER", "LOCATION", "EMAIL_ADDRESS", "US_SSN", "MRN"]

    def scrub(text: str) -> str:
        found = analyzer.analyze(text=text, entities=ENTITIES, language="en")
        return anonymizer.anonymize(text=text, analyzer_results=found,
                                    operators={"DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"})}).text

    notes["noteText"] = notes["noteText"].map(scrub)
    presidio_version = __import__("presidio_analyzer").__version__
except ImportError:
    print("Presidio not installed here; in Fabric it comes from the environment. Free text is withheld from this extract.")
    notes["noteText"] = None
    presidio_version = "not installed"
print(notes.to_string(index=False))

# %% [markdown]
# ## Release checks, report and write

# %%
extract["noteText"] = None                                       # notes are released only when the study approval covers them
release = extract[["studyId"] + [c for c in APPROVED_COLUMNS if c in extract.columns]]
problems = check_release(release)
report = {"studyId": STUDY_ID, "createdAt": datetime.now(timezone.utc).isoformat(), "rows": len(release),
          "participants": int(release["studyId"].nunique()), "linkVersion": version, "method": "HIPAA Safe Harbor",
          "checks": problems or ["all checks passed"], "presidioVersion": presidio_version,
          "lineage": "lh_gold_quality.factVisit + lh_silver_identity.dimPatientSource via happy_platform.deid", "approvedBy": None}
print(json.dumps(report, indent=1))

if problems:
    log.finish(status="Blocked", details="; ".join(problems))
    raise RuntimeError("Release blocked: " + "; ".join(problems))
if not USE_SAMPLES:
    spark.createDataFrame(crosswalk).write.mode("append").saveAsTable(f"{RESTRICTED}.studyCrosswalk_{STUDY_ID.replace('-', '_')}")
    spark.createDataFrame(pd.DataFrame([{"studyId": STUDY_ID, "reportJson": json.dumps(report), "status": "awaiting privacy officer"}])) \
         .write.mode("append").saveAsTable(f"{RESEARCH}.releaseReport")
    # the extract itself is written by the release pipeline only after the privacy officer approves the report
log.finish(rows_written=len(release), details="awaiting privacy officer sign-off")
