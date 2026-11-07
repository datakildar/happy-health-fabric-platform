# %% [markdown]
# # 03 – Patient matching with Splink and link-version publishing
#
# **Steps (docs/patient-matching.md)**
# 1. Standardize the demographic fields of every source record (Epic, MEDITECH, lab, pharmacy, claims).
# 2. Exact rules first: the same record number in the same system is always the same person.
# 3. Splink (Fellegi-Sunter): block on birth date or surname + ZIP, compare each field, train the weights on Happy Health's own data, score each pair.
# 4. Read the thresholds from the MDM settings (Profisee): link automatically above the upper threshold, send the middle band to the steward review queue, keep the rest separate.
# 5. Apply steward decisions from the review queue (they override scores either way).
# 6. Cluster the accepted links into people, keeping person IDs stable (`happy_platform.identity.assign_person_ids`).
# 7. Publish a new link version only if something changed: close old link rows, add new ones, validate, then flip the control row to *published*.
#
# **Pinned versions:** Splink 4.x, running on Fabric Spark through `SparkAPI`. Moving to Splink 5 is a planned change, tested against the labelled sample first.
#
# With `USE_SAMPLES = True` steps 1–5 run on the 43 sample records (training a model on 43 records is only a demonstration), and step 7 replays the sample's version 8 split so you can see the publish logic.

# %% tags=["parameters"]
USE_SAMPLES = True
SAMPLES_PATH = "../samples"                       # in Fabric: /lakehouse/default/Files/samples
MDM_SETTINGS_PATH = "../templates/mdm_settings.json"
SILVER = "lh_silver"
IDENTITY = "lh_silver_identity"
MATCHING_RUN_ID = "MR-local"
PIPELINE_RUN_ID = ""

# %%
import json
from datetime import datetime, timezone

import pandas as pd
from pyspark.sql import SparkSession, functions as F

from happy_platform.audit import RunLogger
from happy_platform.identity import assign_person_ids, latest_published, publish_link_version, resolve_person, validate_links

try:
    spark
except NameError:
    spark = SparkSession.builder.appName("happy-03").getOrCreate()

log = RunLogger("03_patient_matching_splink", matchingRunId=MATCHING_RUN_ID, pipelineRunId=PIPELINE_RUN_ID)

if USE_SAMPLES:
    from happy_platform.samples import load_identity
    ident = load_identity(SAMPLES_PATH)
    settings = json.load(open(MDM_SETTINGS_PATH))
    records = spark.createDataFrame(ident["dimPatientSource"])
    review = pd.read_csv(f"{SAMPLES_PATH}/silver/identity/reviewQueue.csv")
else:
    ident = {t: spark.table(f"{IDENTITY}.{t}").toPandas() for t in ("dimPatientSource", "dimPerson", "bridgePatientLinkHistory", "linkVersion")}
    settings = json.loads(spark.table("lh_mdm.matchingSettings").where("status = 'approved'").orderBy(F.desc("approvedAt")).first()["settingsJson"])
    records = spark.table(f"{IDENTITY}.dimPatientSource")
    review = spark.table(f"{IDENTITY}.reviewQueue").where("decision IS NOT NULL AND publishedInLinkVersion IS NULL").toPandas()

AUTO_LINK, REVIEW_FROM = settings["thresholds"]["autoLink"], settings["thresholds"]["reviewFrom"]
print(f"MDM settings {settings['version']}: auto-link >= {AUTO_LINK}, review {REVIEW_FROM}–{AUTO_LINK}")

# %% [markdown]
# ## 1. Standardize

# %%
std = (records
    .withColumn("firstName", F.upper(F.regexp_replace(F.trim("firstName"), r"[^A-Za-z]", "")))
    .withColumn("lastName", F.upper(F.regexp_replace(F.trim("lastName"), r"[^A-Za-z\- ]", "")))
    .withColumn("birthDate", F.to_date("birthDate"))
    .withColumn("zip", F.substring(F.regexp_replace("zip", r"\D", ""), 1, 5))
    .withColumn("sex", F.upper("sex"))
    .select("sourcePatientKey", "sourceSystem", "firstName", "lastName", "birthDate", "sex", "zip"))
std.cache().count()

# %% [markdown]
# ## 3. Splink model: blocking, comparisons, training, scoring

# %%
import splink.comparison_library as cl
from splink import Linker, SettingsCreator, SparkAPI, block_on

splink_settings = SettingsCreator(
    link_type="dedupe_only",                         # one combined table, so duplicates inside one system are found too
    unique_id_column_name="sourcePatientKey",
    blocking_rules_to_generate_predictions=[block_on("birthDate"), block_on("lastName", "zip")],
    comparisons=[
        cl.NameComparison("firstName").configure(term_frequency_adjustments=True),
        cl.NameComparison("lastName").configure(term_frequency_adjustments=True),   # a common name counts for less
        cl.DateOfBirthComparison("birthDate", input_is_string=False),
        cl.ExactMatch("sex"),
        cl.ExactMatch("zip"),
    ],
    retain_intermediate_calculation_columns=True,
)
linker = Linker(std, splink_settings, SparkAPI(spark_session=spark))

with log.step("train"):
    linker.training.estimate_probability_two_random_records_match([block_on("firstName", "lastName", "birthDate")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=1e7)
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("birthDate"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("lastName", "zip"))

with log.step("predict"):
    predictions = linker.inference.predict(threshold_match_probability=0.01)
    pairs = predictions.as_spark_dataframe()

scored = (pairs.select(F.col("sourcePatientKey_l").alias("recordA"), F.col("sourcePatientKey_r").alias("recordB"),
                       "match_weight", "match_probability")
    .withColumn("outcome", F.when(F.col("match_probability") >= AUTO_LINK, "auto-link")
                            .when(F.col("match_probability") >= REVIEW_FROM, "review").otherwise("separate")))
scored.groupBy("outcome").count().show()

# %% [markdown]
# ## 4–5. Review queue and steward decisions
# Middle-band pairs are written to the review queue. Steward decisions already made override the scores: *link* forces probability 1, *split* forces 0.

# %%
new_reviews = scored.where("outcome = 'review'").withColumn("matchingRunId", F.lit(MATCHING_RUN_ID))
if not USE_SAMPLES:
    new_reviews.write.mode("append").saveAsTable(f"{IDENTITY}.reviewQueueStaging")

decisions = spark.createDataFrame(review[["recordA", "recordB", "decision"]]) if len(review) else None
edges = scored.where("outcome = 'auto-link'").select("recordA", "recordB", "match_probability")
if decisions is not None:
    linked = decisions.where(F.col("decision").startswith("Same person")).select("recordA", "recordB", F.lit(1.0).alias("match_probability"))
    split = decisions.where(F.col("decision").startswith("Different")).select("recordA", "recordB")
    edges = edges.join(split, ["recordA", "recordB"], "left_anti").join(
        split.select(F.col("recordB").alias("recordA"), F.col("recordA").alias("recordB")), ["recordA", "recordB"], "left_anti").unionByName(linked)

# %% [markdown]
# ## 6. Cluster accepted links into people
# Connected components over the accepted edges (Splink's clustering on a registered edge table).

# %%
edge_table = linker.table_management.register_table(
    edges.select(F.col("recordA").alias("sourcePatientKey_l"), F.col("recordB").alias("sourcePatientKey_r"), "match_probability"),
    "happy_accepted_edges", overwrite=True)
clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(edge_table, threshold_match_probability=0.5).as_pandas_dataframe()
cluster_of = dict(zip(clusters["sourcePatientKey"], clusters["cluster_id"]))

links, persons, control = ident["bridgePatientLinkHistory"], ident["dimPerson"], ident["linkVersion"]
latest = latest_published(control)
proposed_person = assign_person_ids(cluster_of, links, persons, latest)
current = resolve_person(links, latest)
changes = {k: p for k, p in proposed_person.items() if current.get(k) != p}
print(f"latest published link version {latest}; {len(changes)} proposed changes")

# %% [markdown]
# ## 7. Publish a new link version (only when something changed)
# The control row is written as *building* first and flipped to *published* last; readers only use published versions, so a half-written version is invisible. On failure the identity tables are restored to their state before the run (Delta `RESTORE`).

# %%
now = datetime.now(timezone.utc).replace(tzinfo=None)
if USE_SAMPLES:
    # replay the sample's split: version 8 moves MEDI-88012 to a new person
    replay_links = links[links["versionFrom"].astype(int) <= 7].copy()
    replay_links.loc[replay_links["versionTo"].astype(int) >= 7, "versionTo"] = 999
    replay_persons = persons[persons["personId"] != "P-0042"].copy()
    replay_persons.loc[replay_persons["personId"] == "P-0012", "status"] = "Active"
    result = publish_link_version(replay_links, replay_persons, control[control["linkVersion"].astype(int) <= 7],
                                  {"MEDI-88012": {"personId": "P-0042", "validFrom": "2026-08-20", "linkMethod": "Steward (split)", "matchProbability": 0.0}},
                                  MATCHING_RUN_ID, settings["version"], now)
    print("published version", result.version, "| changed", result.changed, "| created", result.created, "| retired", result.retired)
    print(result.links.tail(3).to_string(index=False))
elif changes:
    from delta.tables import DeltaTable
    before = {t: spark.sql(f"DESCRIBE HISTORY {IDENTITY}.{t} LIMIT 1").first()["version"] for t in ("bridgePatientLinkHistory", "dimPerson")}
    proposed = {k: {"personId": p, "validFrom": now.date(), "linkMethod": "Scored", "matchProbability": None} for k, p in changes.items()}
    result = publish_link_version(links, persons, control, proposed, MATCHING_RUN_ID, settings["version"], now)
    n = result.version
    spark.createDataFrame(pd.DataFrame([{**result.control.iloc[-1].to_dict(), "status": "building"}])).write.mode("append").saveAsTable(f"{IDENTITY}.linkVersion")
    try:
        touched = result.links[(result.links["versionTo"].astype(int) == n - 1) | (result.links["versionFrom"].astype(int) == n)]
        (DeltaTable.forName(spark, f"{IDENTITY}.bridgePatientLinkHistory").alias("t")
            .merge(spark.createDataFrame(touched).alias("s"), "t.linkId = s.linkId")
            .whenMatchedUpdate(set={"versionTo": "s.versionTo"}).whenNotMatchedInsertAll().execute())
        (DeltaTable.forName(spark, f"{IDENTITY}.dimPerson").alias("t")
            .merge(spark.createDataFrame(result.persons).alias("s"), "t.personId = s.personId")
            .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
        validate_links(spark.table(f"{IDENTITY}.bridgePatientLinkHistory").toPandas(), spark.table(f"{IDENTITY}.dimPerson").toPandas(), n)
        spark.sql(f"UPDATE {IDENTITY}.linkVersion SET status = 'published', publishedAt = current_timestamp() WHERE linkVersion = {n}")
        log.finish(rows_written=len(touched), details=f"published link version {n}")
    except Exception:
        for t, v in before.items():
            spark.sql(f"RESTORE TABLE {IDENTITY}.{t} TO VERSION AS OF {v}")
        spark.sql(f"UPDATE {IDENTITY}.linkVersion SET status = 'failed' WHERE linkVersion = {n}")
        raise
else:
    log.finish(details="no change: no new link version")
    print("No identity change tonight: no new link version.")
