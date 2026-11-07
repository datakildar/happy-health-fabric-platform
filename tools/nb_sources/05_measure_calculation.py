# %% [markdown]
# # 05 – Calculate the five CMS measures for a calculation run
#
# **Run pinning.** A new run records the latest *published* patient-link version, the MDM settings version and the code version in `dimCalculationRun` before any calculation starts. Every step reads the link version from that row, so a version published mid-run can't change the result, and a re-run reproduces it exactly. Submitted runs are frozen: this notebook refuses to overwrite them.
#
# **Generalized results.** Every measure writes the same shape to `factMeasureResult` (CMS population model: initial population, denominator or measure population, exclusion, exception, numerator, observation, stratum). `factMeasureSummary` turns those rows into a rate (proportion measures) or a median (continuous-variable measures) per hospital and stratum. A new measure is a new `dimMeasure` row plus logic that emits standard rows.
#
# | Measure | Scoring | Result on the synthetic data (run R-2026Q3-01, link version 7) |
# |---|---|---|
# | READM-30 readmission | Proportion | 6 / 42 = 14.3% (11.9% in R-2026Q3-02, after the split in version 8) |
# | SEP-1 sepsis bundle | Proportion | 5 / 10 = 50% |
# | ED-T2P time to provider | Continuous | median 46.5 min |
# | OP-18 arrival to departure | Continuous | median 207 min (OP-18b), 127.5 min (OP-18c) |
# | OP-22 left without being seen | Proportion | 3 / 41 = 7.3% |
#
# The pandas reference (`src/happy_platform/measures.py`) is tested against every row of the workbook; the last cell here reconciles the Spark output with it.

# %% tags=["parameters"]
USE_SAMPLES = True
SAMPLES_PATH = "../samples"                       # in Fabric: Files/samples (Spark path in the default lakehouse)
GOLD = "lh_gold_quality"
IDENTITY = "lh_silver_identity"          # read through a OneLake shortcut in production
RUN_ID = "R-2026Q3-01"                   # an existing run to (re)calculate, or a new id to create
PERIOD_START = "2026-07-01"              # used only when RUN_ID is new
PERIOD_END = "2026-09-30"
CODE_VERSION = "measures v1.4.0"
PIPELINE_RUN_ID = ""

# measure settings (versioned in the MDM source in production)
WINDOW_DAYS, MIN_AGE, SEP_3H, SEP_6H, LACT_REPEAT, LACT_FLUIDS, FLUID_ML_KG = 30, 18, 3, 6, 2, 4, 30

# %%
from pyspark.sql import SparkSession, functions as F, Window

from happy_platform.audit import RunLogger

try:
    spark
except NameError:
    spark = (SparkSession.builder.appName("happy-05")
             .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
             .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog").getOrCreate())
spark.conf.set("spark.sql.session.timeZone", "UTC")     # timestamps in gold are hospital local wall-clock times

TS = ["admitDateTime", "dischargeDateTime", "arrivalDateTime", "triageDateTime", "providerSeenDateTime", "roomAssignedDateTime",
      "decisionToAdmitDateTime", "departureDateTime", "timeZero", "initialLactateTime", "bloodCultureTime", "antibioticStartTime",
      "repeatLactateTime", "crystalloidStartTime", "vasopressorStartTime", "comfortCareTime", "runDateTime", "recordedAt"]

def read(layer, name):
    if not USE_SAMPLES:
        return spark.table(f"{IDENTITY if layer == 'identity' else GOLD}.{name}")
    path = f"{SAMPLES_PATH}/silver/identity/{name}.csv" if layer == "identity" else f"{SAMPLES_PATH}/gold/{name}.csv"
    df = spark.read.option("header", True).option("inferSchema", True).csv(path)
    return df.select([F.col(c).cast("timestamp").alias(c) if c in TS else F.col(c) for c in df.columns])

visit, ed, sepsis, dx = read("gold", "factVisit"), read("gold", "factEdVisit"), read("gold", "factSepsisEpisode"), read("gold", "bridgeDiagnosis")
runs, measures = read("gold", "dimCalculationRun"), read("gold", "dimMeasure")
patients, links, control = read("identity", "dimPatientSource"), read("identity", "bridgePatientLinkHistory"), read("identity", "linkVersion")

# %% [markdown]
# ## Pin the run

# %%
existing = runs.where(F.col("runId") == RUN_ID).first()
if existing is None:
    latest = control.where("status = 'published'").agg(F.max("linkVersion")).first()[0]
    run = {"runId": RUN_ID, "periodStart": PERIOD_START, "periodEnd": PERIOD_END, "linkVersion": int(latest),
           "mdmSettingsVersion": control.where(F.col("linkVersion") == latest).first()["mdmSettingsVersion"],
           "codeVersion": CODE_VERSION, "status": "Draft"}
    if not USE_SAMPLES:
        spark.createDataFrame([run]).withColumn("runDateTime", F.current_timestamp()).write.mode("append").saveAsTable(f"{GOLD}.dimCalculationRun")
else:
    run = existing.asDict()
    if str(run["status"]).startswith("Submitted") and not USE_SAMPLES:
        raise RuntimeError(f"{RUN_ID} is submitted and frozen; create a new run instead")

V = int(run["linkVersion"])
P0 = F.to_timestamp(F.lit(str(run["periodStart"])[:10]))
P1 = F.to_timestamp(F.date_add(F.to_date(F.lit(str(run["periodEnd"])[:10])), 1))   # periodEnd is inclusive
PERIOD = f"{str(run['periodStart'])[:4]}-Q{(int(str(run['periodStart'])[5:7]) + 2) // 3}"
log = RunLogger("05_measure_calculation", calcRunId=RUN_ID, linkVersion=V, pipelineRunId=PIPELINE_RUN_ID)
print(f"Run {RUN_ID}: link version {V}, period {run['periodStart']} – {run['periodEnd']}")

# person for each source record AT THE PINNED VERSION (exactly one row per record)
person = links.where((F.col("versionFrom") <= V) & (F.col("versionTo") >= V)).select("sourcePatientKey", "personId")
assert person.groupBy("sourcePatientKey").count().where("count > 1").count() == 0, "link history broken: two rows for one record"
birth = patients.select("sourcePatientKey", F.to_date("birthDate").alias("birthDate"))

def in_period(c):
    return (F.col(c) >= P0) & (F.col(c) < P1)

def age_at(c):
    return F.floor(F.months_between(F.to_date(F.col(c)), F.col("birthDate")) / 12)

def elapsed(start, end, unit_seconds, digits):
    """Rounded elapsed time, half-up, computed in decimals so .5 boundaries round exactly as in Excel."""
    secs = (F.unix_timestamp(end) - F.unix_timestamp(start)).cast("decimal(20,0)")
    return F.round(secs / F.lit(unit_seconds).cast("decimal(20,0)"), digits).cast("double")

def hosp(c):
    return F.substring(F.col(c), 1, 3)

def flag(c):
    return F.coalesce(c, F.lit(False))

# %% [markdown]
# ## 1. READM-30 – 30-day readmission to any Happy Health hospital (Epic or MEDITECH)

# %%
ip = visit.where("patientClass = 'Inpatient'").join(person, "sourcePatientKey").join(birth, "sourcePatientKey")
later = ip.where("plannedAdmission = 'N'").select(F.col("personId").alias("p2"), F.col("admitDateTime").alias("nextAdmit"))
nxt = (ip.join(later, (ip.personId == later.p2) & (later.nextAdmit > ip.dischargeDateTime), "left")
         .groupBy("visitKey").agg(F.min("nextAdmit").alias("nextAdmit")))
readm = (ip.join(nxt, "visitKey", "left")
    .withColumn("ip", in_period("dischargeDateTime"))
    .withColumn("reason", F.when(~F.col("ip"), "Discharged outside period")
                           .when(age_at("admitDateTime") < MIN_AGE, "Under 18")
                           .when(F.col("dischargeDisposition") == "Expired", "Died in hospital")
                           .when(F.col("dischargeDisposition") == "Transferred to acute", "Transferred to another hospital")
                           .when(F.col("dischargeDisposition") == "Left AMA", "Left against medical advice"))
    .withColumn("den", F.col("ip") & F.col("reason").isNull())
    .withColumn("obs", elapsed("dischargeDateTime", "nextAdmit", 86400, 1))
    .select(F.lit("READM-30").alias("measureId"), hosp("locationKey").alias("hospital"), "sourcePatientKey",
            F.col("visitKey").alias("eventKey"), F.lit("All").alias("stratum"), "ip", "den", "reason",
            flag(F.col("den") & (F.col("obs") <= WINDOW_DAYS)).cast("int").alias("inNumerator"),
            F.col("obs").alias("observationValue"), F.lit("days to readmission").alias("observationUnit")))

# %% [markdown]
# ## 2. SEP-1 – severe sepsis / septic shock bundle (all-or-nothing)

# %%
def hrs(c, digits=2):
    return elapsed("timeZero", c, 3600, digits)

sep = (sepsis.join(visit.select("visitKey", "locationKey", "dischargeDateTime"), "visitKey").join(birth, "sourcePatientKey")
    .withColumn("ip", in_period("timeZero"))
    .withColumn("reason", F.when(~F.col("ip"), "Outside period")
                           .when(age_at("timeZero") < MIN_AGE, "Under 18")
                           .when(F.col("transferInFromAcute") == "Y", "Transferred in from another hospital")
                           .when(hrs("comfortCareTime") <= SEP_6H, "Comfort care within 6 h")
                           .when(hrs("dischargeDateTime", 1) < SEP_6H, "Discharged within 6 h"))
    .withColumn("den", F.col("ip") & F.col("reason").isNull())
    .withColumn("lactOK", flag(hrs("initialLactateTime") <= SEP_3H))
    .withColumn("cultOK", flag((hrs("bloodCultureTime") <= hrs("antibioticStartTime")) & (hrs("bloodCultureTime") <= SEP_3H)))
    .withColumn("abxOK", flag(hrs("antibioticStartTime") <= SEP_3H))
    .withColumn("repOK", flag(~(F.col("initialLactateValue") > LACT_REPEAT)) | flag(hrs("repeatLactateTime") <= SEP_6H))
    .withColumn("fluNeeded", (F.col("severity") == "Septic shock") | (F.col("initialLactateValue") >= LACT_FLUIDS))
    .withColumn("fluOK", flag(~F.col("fluNeeded")) | flag((F.coalesce("crystalloidVolumeMl", F.lit(0)) >= F.col("weightKg") * FLUID_ML_KG)
                                                   & (hrs("crystalloidStartTime") <= SEP_3H)))
    .withColumn("vasOK", flag(F.col("persistentHypotension") != "Y") | flag(hrs("vasopressorStartTime") <= SEP_6H))
    .select(F.lit("SEP-1").alias("measureId"), hosp("locationKey").alias("hospital"), "sourcePatientKey",
            F.col("episodeKey").alias("eventKey"), F.lit("All").alias("stratum"), "ip", "den", "reason",
            (F.col("den") & F.col("lactOK") & F.col("cultOK") & F.col("abxOK") & F.col("repOK") & F.col("fluOK") & F.col("vasOK")).cast("int").alias("inNumerator"),
            F.lit(None).cast("double").alias("observationValue"), F.lit(None).cast("string").alias("observationUnit")))

# %% [markdown]
# ## 3–5. ED measures: time to provider, OP-18 (two strata), OP-22

# %%
mental = dx.where("isMentalHealth > 0").select("visitKey").distinct().withColumn("mh", F.lit(True))
edv = ed.join(mental, "visitKey", "left").withColumn("ip", in_period("arrivalDateTime"))

t2p = (edv.withColumn("reason", F.when(~F.col("ip"), "Outside period").when(F.col("providerSeenDateTime").isNull(), "Left without being seen"))
    .withColumn("den", F.col("ip") & F.col("reason").isNull())
    .select(F.lit("ED-T2P").alias("measureId"), hosp("locationKey").alias("hospital"), "sourcePatientKey", F.col("edVisitKey").alias("eventKey"),
            F.lit("All").alias("stratum"), "ip", "den", "reason", F.lit(None).cast("int").alias("inNumerator"),
            F.when(F.col("den"), elapsed("arrivalDateTime", "providerSeenDateTime", 60, 0)).alias("observationValue"),
            F.lit("minutes").alias("observationUnit")))

op18 = (edv.withColumn("reason", F.when(~F.col("ip"), "Outside period")
                                  .when(F.col("edDisposition") != "Discharged", F.concat(F.lit("Not discharged ("), F.col("edDisposition"), F.lit(")"))))
    .withColumn("den", F.col("ip") & F.col("reason").isNull())
    .select(F.lit("OP-18").alias("measureId"), hosp("locationKey").alias("hospital"), "sourcePatientKey", F.col("edVisitKey").alias("eventKey"),
            F.when(F.col("mh"), "Mental health (OP-18c)").otherwise("Main (OP-18b)").alias("stratum"), "ip", "den", "reason",
            F.lit(None).cast("int").alias("inNumerator"),
            F.when(F.col("den"), elapsed("arrivalDateTime", "departureDateTime", 60, 0)).alias("observationValue"),
            F.lit("minutes").alias("observationUnit")))

op22 = (edv.withColumn("reason", F.when(~F.col("ip"), "Outside period")).withColumn("den", F.col("ip"))
    .select(F.lit("OP-22").alias("measureId"), hosp("locationKey").alias("hospital"), "sourcePatientKey", F.col("edVisitKey").alias("eventKey"),
            F.lit("All").alias("stratum"), "ip", "den", "reason", (F.col("den") & (F.col("edDisposition") == "LWBS")).cast("int").alias("inNumerator"),
            F.lit(None).cast("double").alias("observationValue"), F.lit(None).cast("string").alias("observationUnit")))

# %% [markdown]
# ## factMeasureResult: one standard shape for every measure

# %%
results = (readm.unionByName(sep).unionByName(t2p).unionByName(op18).unionByName(op22)
    .join(measures.select("measureId", "measureKey", "scoringType"), "measureId")
    .select(F.lit(RUN_ID).alias("runId"), "measureKey", "measureId", "scoringType", F.lit(PERIOD).alias("reportingPeriod"), "hospital",
            "sourcePatientKey", "eventKey", "stratum", F.col("ip").cast("int").alias("inInitialPopulation"),
            F.col("den").cast("int").alias("inDenominatorOrMeasurePop"), (F.col("ip") & F.col("reason").isNotNull()).cast("int").alias("isExclusion"),
            F.lit(0).alias("isException"), F.col("reason").alias("exclusionReason"), "inNumerator", "observationValue", "observationUnit",
            F.lit(None).cast("double").alias("expectedValue"))).cache()

# %% [markdown]
# ## factMeasureSummary: the scoring type picks a rate or a median

# %%
hospitals = [r[0] for r in read("gold", "dimLocation").select(F.substring("locationKey", 1, 3)).distinct().orderBy(1).collect()]
specs = [(m, "All") for m in ("READM-30", "SEP-1", "ED-T2P", "OP-22")] + [("OP-18", "Main (OP-18b)")]
cells = [(m, h, s) for m, s in specs for h in ["ALL"] + hospitals] + [("OP-18", "ALL", "Mental health (OP-18c)")]
grid = spark.createDataFrame(cells, "measureId string, hospital string, stratum string")

agg = lambda df: df.agg(
    F.sum("inInitialPopulation").alias("initialPopulation"), F.sum("isExclusion").alias("exclusions"),
    F.sum("inDenominatorOrMeasurePop").alias("denominatorOrMeasurePop"),
    F.sum(F.when(F.col("inDenominatorOrMeasurePop") == 1, F.col("inNumerator"))).alias("numerator"),
    F.expr("percentile(CASE WHEN inDenominatorOrMeasurePop = 1 THEN observationValue END, 0.5)").alias("observationMedian"))
by_hosp = agg(results.groupBy("measureId", "hospital", "stratum"))
all_main = agg(results.where("stratum <> 'Mental health (OP-18c)'").groupBy("measureId")).withColumn("hospital", F.lit("ALL"))
all_main = all_main.join(grid.where("hospital = 'ALL' AND stratum <> 'Mental health (OP-18c)'"), ["measureId", "hospital"])
all_mh = agg(results.where("stratum = 'Mental health (OP-18c)'").groupBy("measureId")).withColumn("hospital", F.lit("ALL")).withColumn("stratum", F.lit("Mental health (OP-18c)"))
stats = by_hosp.where("hospital <> 'ALL'").unionByName(all_main).unionByName(all_mh)

summary = (grid.join(stats, ["measureId", "hospital", "stratum"], "left").join(measures.select("measureId", "measureKey", "scoringType"), "measureId")
    .na.fill(0, ["initialPopulation", "exclusions", "denominatorOrMeasurePop"])
    .withColumn("numerator", F.when(F.col("scoringType") == "Proportion", F.coalesce("numerator", F.lit(0))))
    .withColumn("observationMedian", F.when(F.col("scoringType") == "Continuous variable", F.col("observationMedian")))
    .withColumn("resultValue", F.when(F.col("scoringType") == "Proportion", F.col("numerator") / F.nullif(F.col("denominatorOrMeasurePop"), F.lit(0)))
                                 .otherwise(F.col("observationMedian")))
    .withColumn("runId", F.lit(RUN_ID)).withColumn("reportingPeriod", F.lit(PERIOD)))

summary.where("hospital = 'ALL'").select("measureId", "stratum", "initialPopulation", "exclusions", "denominatorOrMeasurePop", "numerator",
                                         F.round("resultValue", 4).alias("resultValue")).orderBy("measureId", "stratum").show(truncate=False)

# %%
if not USE_SAMPLES:
    with log.step("write results"):
        for name, df in (("factMeasureResult", results), ("factMeasureSummary", summary)):
            (df.write.format("delta").mode("overwrite").option("replaceWhere", f"runId = '{RUN_ID}'")   # only this run's rows
               .saveAsTable(f"{GOLD}.{name}"))
    log.finish(rows_written=results.count())

# %%
# Reconciliation with the workbook (sample mode): every summary cell must match samples/gold/factMeasureSummary.csv
if USE_SAMPLES and RUN_ID == "R-2026Q3-01":
    expected = spark.read.option("header", True).option("inferSchema", True).csv(f"{SAMPLES_PATH}/gold/factMeasureSummary.csv")
    cmp = (summary.alias("a").join(expected.alias("b"), ["measureId", "hospital", "stratum"], "full")
           .where(~F.expr("a.denominatorOrMeasurePop <=> b.denominatorOrMeasurePop") | ~F.expr("a.initialPopulation <=> b.initialPopulation")
                  | (F.abs(F.coalesce(F.col("a.resultValue"), F.lit(-1.0)) - F.coalesce(F.col("b.resultValue"), F.lit(-1.0))) > 1e-9)))
    n = cmp.count()
    print("Reconciliation:", "all 91 summary rows match the workbook" if n == 0 else f"{n} rows differ")
    if n:
        cmp.show(truncate=False)
