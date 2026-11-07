# %% [markdown]
# # 01 – MEDITECH HL7v2 nightly files → FHIR → bronze
#
# **What it does**
# 1. Reads last night's MEDITECH batch files from the landing folder (a OneLake shortcut to the SFTP drop).
# 2. Splits each file into messages and picks the FHIR Converter template from the message type (MSH-9), e.g. `ADT^A03` → `ADT_A03`.
# 3. Calls Happy Health's FHIR Converter service for each message and writes the resulting resources as NDJSON, one file per resource type, so MEDITECH follows exactly the same path as Epic.
# 4. Sends anything that fails to `lh_monitoring.conversionErrorLog` with the message control ID, so nothing is dropped silently.
# 5. Reads the assumed `ZET` segment (ED tracking events, a requested MEDITECH feed addition) with the reference parser, because the converter templates don't cover custom Z segments.
#
# **Known converter gaps handled here** (see `docs/architecture-decisions.md`, ADR-004): no RAS template (medication administration), no Z-segment support, encounter IDs need PV1-19 with an assigning authority, and HL7v2 times have no UTC offset, so the converter's time zone setting must be the hospital's.
#
# With `USE_SAMPLES = True` the notebook skips the converter and shows what the reference parser reads from `samples/bronze/meditech_hl7v2/`.

# %% tags=["parameters"]
USE_SAMPLES = True
SAMPLES_PATH = "../samples"                       # in Fabric: /lakehouse/default/Files/samples
LANDING_PATH = "/lakehouse/default/Files/landing/meditech"             # shortcut to the nightly SFTP drop
BRONZE_ROOT = "/lakehouse/default/Files/bronze/meditech_fhir"
CONVERTER_URL = "https://fhir-converter.happy.internal/convertToFhir?api-version=2024-05-01-preview"   # check your deployed version
LOCAL_TIME_ZONE = "America/New_York"
BATCH_DATE = ""                                                      # yyyymmdd; empty = yesterday
PIPELINE_RUN_ID = ""

# %%
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from happy_platform.audit import RunLogger
from happy_platform.hl7v2 import Message, parse_batch, to_silver

batch_date = BATCH_DATE or f"{date.today() - timedelta(days=1):%Y%m%d}"
folder = Path(SAMPLES_PATH) / "bronze" / "meditech_hl7v2" if USE_SAMPLES else Path(LANDING_PATH) / batch_date
files = sorted(folder.glob("*.hl7"))
messages = [m for f in files for m in parse_batch(f.read_text())]
log = RunLogger("01_meditech_hl7v2_to_fhir", pipelineRunId=PIPELINE_RUN_ID, batchDate=batch_date)
print(f"{len(files)} files, {len(messages)} messages")

# %%
TEMPLATES = {"ADT^A01": "ADT_A01", "ADT^A03": "ADT_A03", "ADT^A04": "ADT_A04", "ADT^A08": "ADT_A08", "ADT^A40": "ADT_A40",
             "ORU^R01": "ORU_R01", "DFT^P03": "DFT_P03", "RDE^O11": "RDE_O11",
             "RAS^O17": None}   # no Microsoft template yet: Happy Health-maintained template to be written (weeks 1–8 of the plan)


def template_for(m: Message) -> str | None:
    msh = m.get("MSH")
    return TEMPLATES.get(f"{Message.field(msh, 9, 1)}^{Message.field(msh, 9, 2)}")


def raw(m: Message) -> str:
    return "\r".join("|".join(seg) for seg in m.segments)


def convert(m: Message) -> tuple[str, dict | str]:
    import requests
    control_id = Message.field(m.get("MSH"), 10)
    tpl = template_for(m)
    if tpl is None:
        return control_id, "no template for this message type"
    body = {"InputDataFormat": "Hl7v2", "RootTemplateName": tpl, "InputDataString": raw(m)}
    r = requests.post(CONVERTER_URL, json=body, timeout=60)
    return (control_id, r.json()) if r.ok else (control_id, f"{r.status_code}: {r.text[:500]}")

# %%
if USE_SAMPLES:
    silver = to_silver(messages)          # what the reference parser reads; the converter path is shown below
    for name, df in silver.items():
        print(name, len(df))
    display(silver["edTrackingEvent"].head()) if "display" in globals() else print(silver["edTrackingEvent"].head())
else:
    out = Path(BRONZE_ROOT) / batch_date
    out.mkdir(parents=True, exist_ok=True)
    by_type, errors = defaultdict(list), []
    with log.step("convert messages"), ThreadPoolExecutor(max_workers=8) as pool:
        for control_id, result in pool.map(convert, messages):
            if isinstance(result, str):
                errors.append({"batchDate": batch_date, "messageControlId": control_id, "error": result})
                continue
            for entry in result.get("result", result).get("entry", []):
                by_type[entry["resource"]["resourceType"]].append(entry["resource"])
    for rtype, resources in by_type.items():
        with open(out / f"{rtype}.ndjson", "w") as f:
            for res in resources:
                f.write(json.dumps(res) + "\n")
    # custom ZET segment -> silver ED tracking events (the converter ignores Z segments)
    ed = to_silver(messages)["edTrackingEvent"]
    spark.createDataFrame(ed).write.mode("append").saveAsTable("lh_silver.edTrackingEventStaging")
    if errors:
        spark.createDataFrame(pd.DataFrame(errors)).write.mode("append").saveAsTable("lh_monitoring.conversionErrorLog")
    log.finish(rows_read=len(messages), rows_written=sum(len(v) for v in by_type.values()), details=f"errors={len(errors)}")
    if errors:
        raise RuntimeError(f"{len(errors)} messages failed to convert; see lh_monitoring.conversionErrorLog")
