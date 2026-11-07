# Workspaces, environments and capacity

> Part of the [Happy Health Fabric platform](../README.md) documentation.

## Environments

| | Dev | UAT | Production |
|---|---|---|---|
| Data | Synthetic only (this repository's samples) | Real patient data, production-level security | Real patient data |
| Capacity | F8, pay-as-you-go, paused nights and weekends | F32, pay-as-you-go, paused outside test windows; F64 for the parallel run (weeks 12–14) | F64, 1-year reservation after 1–2 months on pay-as-you-go |
| Who writes | Engineers | Deployment pipeline and service principals | Deployment pipeline and service principals only |
| Promotion | Git branch → pull request | Fabric deployment pipeline, approval gate | Fabric deployment pipeline, approval gate |

Workspaces per environment are listed in [naming-conventions.md](naming-conventions.md). Each environment has the same items with the same names; deployment rules swap lakehouse and connection IDs.

## Capacity sizing

| Environment | Capacity | Billing | Why |
|---|---|---|---|
| Production: Power BI and gold | F64 | 1-year reservation after 1–2 months on pay-as-you-go | Free viewers for about 500 report users; Direct Lake up to 25 GB and 1.5 billion rows per table |
| Production: loads and notebooks | Autoscale billing for Spark, capped at 64–128 CU | Pay per use | Nightly jobs don't take capacity from reports |
| UAT | F32; F64 for the parallel run | Pay-as-you-go, paused outside test windows | Real data with production security; performance tested at the production size |
| Dev | F8 | Pay-as-you-go, paused nights and weekends | Synthetic data only |

**Assumptions** (the problem statement gives no volumes; confirm in the first weeks): 17 hospitals and about 150 clinics; about 2.5 million patients, 200,000 admissions, 750,000 ED visits and 3 million clinic visits a year; about 500 million lab and vital-sign results a year (2.5 billion over five years); 5–10 TB of raw FHIR in bronze; about 500 report viewers and 40 report creators.

**Why F64 in production.** From F64 up, people who only view reports need a free license. Below it every viewer needs Power BI Pro, about $14 a month each, roughly $7,000 a month for 500 viewers, more than the capacity itself. F64 also raises Direct Lake limits to 25 GB of memory and 1.5 billion rows per table (F32: 10 GB and 300 million rows).

**The lab-results history.** About 2.5 billion rows over five years won't fit one Direct Lake table on F64. It stays in the lakehouse and models read summarized tables (the quality models are small, and the patient 360 keeps only the latest values). A model that truly needs every row would need F128 or an import model with aggregations.

**Why autoscale billing for Spark.** Nightly notebooks (Healthcare Data Solutions loads, Splink, measures, the Epic export) are billed separately on demand and don't consume the F64 that reports use. Background jobs are smoothed over 24 hours of capacity, so keeping them off the capacity protects report performance better than buying a bigger SKU. Cap it at 64–128 CU; nightly runs of 2–3 hours cost roughly $250–350 a month. The one-time history load is billed the same way.

**Rough monthly cost** (US list prices from a 2026 pricing guide, before discounts):

| Item | Monthly |
|---|---|
| F64 reserved (about $8,400 on pay-as-you-go) | about $5,000 |
| On-demand Spark | about $300 |
| UAT F32, on about 40% of the time | about $1,700 |
| Dev F8, on about 50% of the time | about $525 |
| OneLake storage, about 8 TB | about $200 |
| Pro licenses for about 40 report creators (unless they have Microsoft 365 E5) | about $560 |
| **Total** | **about $8,300** |

If a separate ETL capacity is required, use an F32 reservation (about $2,500) beside the F64, and keep gold in the F64 workspace: data in a paused capacity's workspace can't be read.

## Capacity guardrails

* Fabric Capacity Metrics app reviewed weekly; alert at 80% sustained use.
* Dev and UAT pause on a schedule; nothing in production pauses.
* Delta maintenance (notebook 07) keeps file counts and Direct Lake framing efficient.
* Cost owner named; monthly review of capacity, Spark and storage spend.
