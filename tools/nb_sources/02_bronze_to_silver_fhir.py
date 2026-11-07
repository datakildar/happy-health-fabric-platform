# %% [markdown]
# # 02 – Bronze FHIR → silver clinical tables
#
# In production, Healthcare Data Solutions flattens the standard FHIR resources into its silver tables. This notebook shows the same mapping for the tables the measures read, and the parts Happy Health adds itself:
# * the ED tracking extension on Encounter (assumed Epic mapping, to confirm),
# * time zones: FHIR instants carry an offset, silver stores hospital local time,
# * source-prefixed patient keys (`EPIC-<MRN>`, `MEDI-<MRN>`),
# * data-quality rules: rows that fail go to a quarantine table instead of silver,
# * upserts with Delta `MERGE`, so re-running a night is safe.
#
# Silver tables written: `patient`, `encounter`, `edTrackingEvent`, `condition` in `lh_silver`.
# The reference implementation is `src/happy_platform/fhir_flatten.py`; `tests/test_pipeline_layers.py` proves bronze and silver samples agree.

# %% tags=["parameters"]
USE_SAMPLES = True
SAMPLES_PATH = "../samples"                       # in Fabric: Files/samples (Spark path in the default lakehouse)
BRONZE_EPIC = "Files/bronze/epic_fhir/*"            # folder per export
SILVER = "lh_silver"
LOCAL_TIME_ZONE = "America/New_York"
PIPELINE_RUN_ID = ""

# %%
from pyspark.sql import SparkSession, functions as F, Window
from delta.tables import DeltaTable

try:
    spark                                            # provided by Fabric
except NameError:
    spark = (SparkSession.builder.appName("happy-02")
             .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
             .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog").getOrCreate())
spark.conf.set("spark.sql.session.timeZone", "UTC")   # parse instants as UTC, then convert explicitly to local time
spark.sql(f"CREATE DATABASE IF NOT EXISTS {SILVER}")

src = f"{SAMPLES_PATH}/bronze/epic_fhir" if USE_SAMPLES else BRONZE_EPIC
patient_raw = spark.read.json(f"{src}/Patient*.ndjson")
encounter_raw = spark.read.json(f"{src}/Encounter*.ndjson")
condition_raw = spark.read.json(f"{src}/Condition*.ndjson")
batch_id = PIPELINE_RUN_ID or "local"

def local(col):
    """FHIR instant with offset -> hospital local wall-clock time."""
    return F.from_utc_timestamp(F.to_timestamp(col), LOCAL_TIME_ZONE)

ED_EXT = "https://fhir.happyhealth.example/StructureDefinition/ed-tracking"
COVERAGE_EXT = "https://fhir.happyhealth.example/StructureDefinition/encounter-coverage"
def ref_id(col):
    return F.element_at(F.split(col, "/"), 2)

# %%
mrn = F.expr("filter(identifier, i -> i.type.text = 'MRN')[0].value")
patient = patient_raw.select(
    F.concat(F.lit("EPIC-"), mrn).alias("patientId"), F.lit("Epic").alias("sourceSystem"), mrn.alias("localRecordNumber"),
    F.col("name")[0]["given"][0].alias("givenName"), F.col("name")[0]["family"].alias("familyName"),
    F.to_date("birthDate").alias("birthDate"), F.col("gender"), F.col("address")[0]["postalCode"].alias("postalCode"))
patient_key = patient_raw.select(F.col("id").alias("fhirPatientId"), F.concat(F.lit("EPIC-"), mrn).alias("patientId"))

enc_id = F.expr("filter(identifier, i -> i.system like '%encounter-id')[0].value")
encounter = (encounter_raw
    .join(patient_key, ref_id(F.col("subject.reference")) == F.col("fhirPatientId"), "left")
    .select(
        enc_id.alias("encounterId"), F.lit("Epic").alias("sourceSystem"), F.col("patientId"),
        F.col("class.code").alias("encounterClass"), ref_id(F.col("location")[0]["location"]["reference"]).alias("locationId"),
        local(F.col("period.start")).alias("periodStart"), local(F.col("period.end")).alias("periodEnd"),
        F.col("hospitalization.dischargeDisposition.text").alias("dischargeDisposition"),
        F.when(F.col("priority.coding")[0]["code"] == "EL", "elective").otherwise("emergency").alias("admissionType"),
        ref_id(F.expr(f"filter(extension, e -> e.url = '{COVERAGE_EXT}')[0].valueReference.reference")).alias("coverageId"),
        ref_id(F.expr("filter(participant, p -> p.type[0].coding[0].code = 'ATND')[0].individual.reference")).alias("attendingPractitionerId")))

ed = F.expr(f"filter(extension, e -> e.url = '{ED_EXT}')[0].extension")
def sub(name, field="valueDateTime"):
    return F.expr(f"filter(edExt, x -> x.url = '{name}')[0].{field}")
ed_tracking = (encounter_raw.select(enc_id.alias("encounterId"), ed.alias("edExt")).where(F.col("edExt").isNotNull())
    .select(sub("trackingId", "valueString").alias("edTrackingId"), "encounterId",
            local(sub("triage")).alias("triageDateTime"), local(sub("providerSeen")).alias("providerSeenDateTime"),
            local(sub("roomAssigned")).alias("roomAssignedDateTime"), local(sub("decisionToAdmit")).alias("decisionToAdmitDateTime"),
            sub("disposition", "valueString").alias("edDisposition"), sub("admittedEncounter", "valueString").alias("admittedEncounterId")))

# principal diagnosis = Encounter.diagnosis.rank 1
ranks = (encounter_raw.select(enc_id.alias("encounterId"), F.explode_outer("diagnosis").alias("d"))
         .select("encounterId", ref_id(F.col("d.condition.reference")).alias("conditionId"), F.col("d.rank").alias("rank")))
condition = (condition_raw.select(F.col("id").alias("conditionId"), F.col("code.coding")[0].alias("c"))
    .join(ranks, "conditionId", "inner")
    .select("encounterId", F.col("c.code").alias("icd10Code"), F.col("c.display").alias("display"),
            F.when(F.col("rank") == 1, "principal").otherwise("secondary").alias("diagnosisRole")))

# %% [markdown]
# ## Data-quality rules
# Rows failing a rule go to `lh_silver.quarantine` with the rule name; they never reach silver or the measures.

# %%
RULES = {
    "encounter": [("missing patient", F.col("patientId").isNull()),
                  ("end before start", F.col("periodEnd") < F.col("periodStart")),
                  ("unknown class", ~F.col("encounterClass").isin("IMP", "EMER", "AMB"))],
    "patient": [("missing birth date", F.col("birthDate").isNull())],
    "edTrackingEvent": [("provider seen before triage", F.col("providerSeenDateTime") < F.col("triageDateTime"))],
}

def split_quality(name, df):
    """Returns (good rows, failed rows with the rule name). A row failing several rules appears once per rule."""
    rules = RULES.get(name, [])
    if not rules:
        return df, None
    failed_any = F.lit(False)
    bad = None
    for rule, cond in rules:
        hit = F.coalesce(cond, F.lit(False))          # a rule that evaluates to null doesn't fail the row
        failed_any = failed_any | hit
        flagged = df.where(hit).withColumn("rule", F.lit(rule))
        bad = flagged if bad is None else bad.unionByName(flagged)
    return df.where(~failed_any), bad

# %%
KEYS = {"patient": ["patientId"], "encounter": ["encounterId"], "edTrackingEvent": ["edTrackingId"],
        "condition": ["encounterId", "icd10Code"]}

def upsert(name, df):
    df = df.withColumn("_sourceSystem", F.lit("Epic")).withColumn("_batchId", F.lit(batch_id)).withColumn("_loadTimestamp", F.current_timestamp())
    good, bad = split_quality(name, df)
    if bad is not None and bad.limit(1).count():
        (bad.withColumn("table", F.lit(name)).select("table", "rule", F.to_json(F.struct(*df.columns)).alias("row"), "_batchId", "_loadTimestamp")
            .write.mode("append").saveAsTable(f"{SILVER}.quarantine"))
    target = f"{SILVER}.{name}"
    if not spark.catalog.tableExists(target):
        good.write.format("delta").saveAsTable(target)
        return good.count()
    cond = " AND ".join(f"t.{k} = s.{k}" for k in KEYS[name])
    (DeltaTable.forName(spark, target).alias("t").merge(good.alias("s"), cond)
        .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
    return good.count()

for name, df in {"patient": patient, "encounter": encounter, "edTrackingEvent": ed_tracking, "condition": condition}.items():
    print(f"{name:16s} {upsert(name, df):>6,} rows merged")

# %%
# Quick look: local times, not UTC
spark.table(f"{SILVER}.encounter").orderBy("encounterId").select("encounterId", "periodStart", "periodEnd", "dischargeDisposition").show(5, truncate=False)
