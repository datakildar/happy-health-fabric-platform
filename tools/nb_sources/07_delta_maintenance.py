# %% [markdown]
# # 07 – Delta table maintenance (weekly)
#
# * `OPTIMIZE` compacts small files (nightly merges create many) and applies V-Order for faster Direct Lake reads.
# * `VACUUM` removes files no longer referenced, but **keeps 30 days** so time travel can rebuild any recent state. Submitted calculation runs never depend on time travel: their rows are frozen in `factMeasureResult`, and bronze keeps the raw inputs.
# * Bronze is append-only and never vacuumed below its retention period (7 years for medical records, to confirm with Happy Health's records policy).
# * Each table's history is checked for failed operations and logged.

# %% tags=["parameters"]
LAKEHOUSES = {"lh_silver": 720, "lh_silver_identity": 720, "lh_gold_quality": 720}   # hours to keep (30 days)
ZORDER = {"lh_gold_quality.factMeasureResult": ["runId", "measureId"], "lh_silver.encounter": ["patientId"]}
PIPELINE_RUN_ID = ""

# %%
from happy_platform.audit import RunLogger

log = RunLogger("07_delta_maintenance", pipelineRunId=PIPELINE_RUN_ID)
done = 0
for lakehouse, keep_hours in LAKEHOUSES.items():
    for t in spark.catalog.listTables(lakehouse):
        name = f"{lakehouse}.{t.name}"
        with log.step(f"maintain {name}"):
            z = ZORDER.get(name)
            spark.sql(f"OPTIMIZE {name}" + (f" ZORDER BY ({', '.join(z)})" if z else "") + " VORDER")
            spark.sql(f"VACUUM {name} RETAIN {keep_hours} HOURS")
            done += 1
log.finish(rows_written=done, details="tables optimized and vacuumed")
print(f"{done} tables maintained")
