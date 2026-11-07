# Relationships in the quality model

All relationships are many-to-one and filter in one direction, from the dimension to the fact.

| From (many) | To (one) | Key |
|---|---|---|
| factVisit | dimLocation | locationKey |
| factVisit | dimPayer | payerKey |
| factVisit | dimPractitioner | attendingPractitionerKey |
| factVisit | dimDateTime | date of admitDateTime |
| factEdVisit | factVisit | visitKey |
| factSepsisEpisode | factVisit | visitKey |
| bridgeDiagnosis | factVisit | visitKey |
| factMeasureResult | dimMeasure | measureKey |
| factMeasureResult | dimCalculationRun | runId |
| factMeasureSummary | dimMeasure | measureKey |
| factMeasureSummary | dimCalculationRun | runId |
| facts | dimPatientSource | sourcePatientKey |

**Identity:** facts join to `dimPatientSource`, not to `dimPerson`. To show results by person, a run-scoped view (`vwPersonForRun`) resolves each source record through `bridgePatientLinkHistory` at the run's pinned link version and is joined in the model on sourcePatientKey. This keeps the model a star while history stays versioned.
