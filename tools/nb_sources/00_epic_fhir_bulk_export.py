# %% [markdown]
# # 00 – Epic FHIR bulk export → bronze
#
# **Runs as:** a plain Python notebook (no Spark), scheduled by `pl_happy_nightly`. Waiting for Epic is cheap here because no Spark cluster sits idle.
#
# **What it does**
# 1. Signs a short-lived token (SMART Backend Services: a JWT signed with Happy Health's private key, RS384) and exchanges it for an access token.
# 2. Starts a `Group/{id}/$export` job and polls the status address until Epic returns the file manifest.
# 3. Downloads each NDJSON file into the bronze lakehouse, unchanged, under `Files/bronze/epic_fhir/<exportId>/`.
# 4. Writes the manifest and one run-log row (logging standard).
#
# **Limits to remember** (confirm for Happy Health's Epic instance): exports are group-based, have no `_since` filter, and by default run once per group per 24 hours. Daily changes may come from Clarity through mirroring instead (see `docs/architecture-decisions.md`, ADR-009).
#
# This notebook can't run against the samples: it needs Epic credentials. The NDJSON it produces looks like `samples/bronze/epic_fhir/`.

# %% tags=["parameters"]
EPIC_BASE_URL = "https://fhir.epic.example.org/api/FHIR/R4"         # Happy Health's Epic FHIR base URL
EPIC_TOKEN_URL = "https://fhir.epic.example.org/oauth2/token"
EPIC_CLIENT_ID = "<backend-app-client-id>"
EPIC_GROUP_IDS = ["<group-id-1>"]                                     # Happy Health-defined patient groups (roughly 1,000 patients each)
RESOURCE_TYPES = "Patient,Encounter,Condition,Observation,MedicationAdministration,Procedure,Coverage"
KEY_VAULT_URL = "https://kv-happy-data-prod.vault.azure.net/"
PRIVATE_KEY_SECRET = "epic-backend-private-key"
POLL_SECONDS = 600                                                   # Epic suggests checking every 10–30 minutes
MAX_WAIT_HOURS = 8
BRONZE_ROOT = "/lakehouse/default/Files/bronze/epic_fhir"           # default lakehouse = lh_bronze
PIPELINE_RUN_ID = ""

# %%
import json, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt          # PyJWT, with the cryptography package for RS384
import requests

from happy_platform.audit import RunLogger   # from the happy_platform wheel attached to the Fabric environment

try:
    import notebookutils                                  # available inside Fabric
    private_key = notebookutils.credentials.getSecret(KEY_VAULT_URL, PRIVATE_KEY_SECRET)
except ImportError:
    raise SystemExit("Run inside Fabric: the private key is read from Key Vault, never stored in the notebook.")

log = RunLogger("00_epic_fhir_bulk_export", pipelineRunId=PIPELINE_RUN_ID)

# %%
def access_token() -> str:
    """SMART Backend Services: sign a 5-minute JWT, exchange it for an access token."""
    now = datetime.now(timezone.utc)
    assertion = jwt.encode(
        {"iss": EPIC_CLIENT_ID, "sub": EPIC_CLIENT_ID, "aud": EPIC_TOKEN_URL, "jti": str(uuid.uuid4()),
         "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp())},
        private_key, algorithm="RS384")
    r = requests.post(EPIC_TOKEN_URL, timeout=60, data={
        "grant_type": "client_credentials", "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion})
    r.raise_for_status()
    return r.json()["access_token"]          # lasts a few minutes: ask for a new one before each call


def headers(**extra):
    return {"Authorization": f"Bearer {access_token()}", "Accept": "application/fhir+json", **extra}

# %%
def start_export(group_id: str) -> str:
    r = requests.get(f"{EPIC_BASE_URL}/Group/{group_id}/$export", params={"_type": RESOURCE_TYPES},
                     headers=headers(Prefer="respond-async"), timeout=120)
    if r.status_code != 202:
        raise RuntimeError(f"export kick-off failed for group {group_id}: {r.status_code} {r.text[:500]}")
    return r.headers["Content-Location"]                 # status address


def wait_for_manifest(status_url: str) -> dict:
    deadline = datetime.now(timezone.utc) + timedelta(hours=MAX_WAIT_HOURS)
    while datetime.now(timezone.utc) < deadline:
        r = requests.get(status_url, headers=headers(), timeout=120)
        if r.status_code == 200:
            return r.json()                              # manifest: {"output": [{"type": "Patient", "url": ...}], "error": [...]}
        if r.status_code != 202:
            raise RuntimeError(f"export failed: {r.status_code} {r.text[:500]}")
        wait = int(r.headers.get("Retry-After", POLL_SECONDS))
        print(f"{datetime.now():%H:%M} still running ({r.headers.get('X-Progress', 'no progress header')}); next check in {wait}s")
        time.sleep(wait)
    raise TimeoutError(f"export not finished after {MAX_WAIT_HOURS} h")


def download(manifest: dict, folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    rows = 0
    for i, item in enumerate(manifest["output"]):
        target = folder / f"{item['type']}.{i:03d}.ndjson"
        with requests.get(item["url"], headers=headers(Accept="application/fhir+ndjson"), stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
        rows += sum(1 for _ in open(target))
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return rows

# %%
total = 0
for group_id in EPIC_GROUP_IDS:
    export_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M}_{group_id}"
    with log.step(f"export group {group_id}"):
        manifest = wait_for_manifest(start_export(group_id))
        if manifest.get("error"):
            print("Epic reported errors for some resources:", manifest["error"])   # kept in manifest.json for the audit trail
        total += download(manifest, Path(BRONZE_ROOT) / export_id)
log.finish(rows_written=total, details=f"groups={len(EPIC_GROUP_IDS)}")
print(f"Downloaded {total:,} resources into bronze")
