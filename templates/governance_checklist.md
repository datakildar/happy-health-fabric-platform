# Go-live governance checklist – Happy Health on Microsoft Fabric

Complete before each production release. Each item has an owner and evidence (link, screenshot or query result) recorded in the release ticket.

## 1. Patient data protection
- [ ] Microsoft business associate agreement covers Fabric, Power BI and Purview for Happy Health's tenant
- [ ] Default sensitivity label "Highly Confidential – PHI" on bronze, silver, identity and gold workspaces; labeling mandatory
- [ ] Purview scan classifies patient-data columns; label inheritance to semantic models, reports and exports verified
- [ ] Data loss prevention policy for Fabric active (alerts on patient data in unlabeled items or exports)
- [ ] No patient data in dev: dev uses the synthetic dataset only

## 2. Access
- [ ] Business users have no Admin, Member or Contributor role in any data workspace (those roles bypass row-level security)
- [ ] Production items are written only by service principals or the workspace identity
- [ ] Semantic models use a fixed identity for Direct Lake, so users can't bypass the model through OneLake or the SQL endpoint
- [ ] Roles tested with "View as role" and with test accounts: de-identified analyst, analyst with grant, department leader, care manager
- [ ] Time-limited patient-data grants run through an Entra access package that expires
- [ ] Quarterly access review scheduled for every group and app audience

## 3. Patient matching
- [ ] MDM settings version approved and recorded; thresholds unchanged since the last labelled-sample test, or retested
- [ ] Precision and recall on the hand-labelled Epic–MEDITECH sample meet the agreed targets
- [ ] Splink version pinned in the environment
- [ ] Every published link version passes validation (one open row per record, no empty persons)
- [ ] Steward review queue staffed; split procedure includes a privacy review

## 4. Measures
- [ ] Each measure's dimMeasure row matches the CMS specification version for the period
- [ ] Parallel run reconciled with last quarter's spreadsheets; every difference explained and signed off by clinical experts
- [ ] Submitted runs marked frozen; notebook 05 refuses to overwrite them
- [ ] Small-number suppression (1–10) applied to anything shared outside the quality team

## 5. Pipelines and audit
- [ ] Every notebook writes notebookRunLog / notebookErrorLog rows (logging standard)
- [ ] Nightly pipeline alerts the on-call channel on failure; retry and timeout set
- [ ] Conversion errors (HL7v2 → FHIR) reviewed daily; none older than 2 days
- [ ] Delta maintenance scheduled; vacuum retention 30 days; bronze retention per records policy
- [ ] Purview audit log and workspace monitoring flowing into the monitoring lakehouse

## 6. Research releases
- [ ] Approved column list per study; Safe Harbor checks pass; Presidio version recorded
- [ ] Study ID crosswalk stored only in lh_restricted
- [ ] Privacy officer signed the release report

## 7. Capacity and cost
- [ ] Capacity Metrics app monitored; alert at 80% sustained use
- [ ] Spark autoscale billing cap set; dev and UAT capacities pause on schedule
- [ ] Named owner for the monthly cost review
