# Pipelines

Fabric data pipelines in the Git-integration folder format (`<name>.DataPipeline/pipeline-content.json`). IDs in angle brackets are replaced per environment by the deployment pipeline's rules.

| Pipeline | Schedule | What it runs |
|---|---|---|
| `pl_happy_nightly` | 02:00 daily (after the MEDITECH files land) | Epic export and MEDITECH conversion in parallel → Healthcare Data Solutions → Happy Health silver tables → patient matching (publishes a link version only when identity changed) → gold → semantic model refresh; Teams alert on failure |
| `pl_happy_measures_quarterly` | Quarterly, or on demand | Notebook 05 for a run ID; a new run pins the latest published link version, an existing run is recalculated exactly |

Rules: concurrency 1 (two matching runs can never take the same link version number), two retries with a two-minute wait, notebooks run as the workspace identity, and every notebook writes the run and error log rows of the logging standard. Delta maintenance (notebook 07) runs weekly on its own schedule.

These are templates written from the Fabric pipeline JSON format: import them through Git integration and check activity types and connection settings in the Fabric UI before the first run.
