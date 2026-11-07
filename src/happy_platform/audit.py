"""Logging standard for every notebook: one run row, plus one row per error.

In Fabric the writer appends to Delta tables in the monitoring lakehouse:
    lh_monitoring.notebookRunLog    runId, notebook, startedAt, finishedAt, status, rowsRead, rowsWritten, linkVersion, calcRunId, details
    lh_monitoring.notebookErrorLog  runId, notebook, loggedAt, step, errorType, message
Locally (tests, laptops) the default writer keeps the rows in memory.

Usage in a notebook:
    log = RunLogger("05_measure_calculation", writer=delta_writer(spark))
    with log.step("calculate READM-30"):
        ...
    log.finish(rows_written=n)
"""
from __future__ import annotations

import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

Writer = Callable[[str, dict], None]


class MemoryWriter:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {"notebookRunLog": [], "notebookErrorLog": []}

    def __call__(self, table: str, row: dict) -> None:
        self.tables[table].append(row)


def delta_writer(spark, lakehouse: str = "lh_monitoring") -> Writer:  # pragma: no cover - needs Spark
    def write(table: str, row: dict) -> None:
        spark.createDataFrame([row]).write.mode("append").option("mergeSchema", "true").saveAsTable(f"{lakehouse}.{table}")
    return write


class RunLogger:
    def __init__(self, notebook: str, writer: Writer | None = None, **context):
        self.notebook = notebook
        self.writer = writer or MemoryWriter()
        self.run_id = str(uuid.uuid4())
        self.started = datetime.now(timezone.utc)
        self.context = context          # e.g. linkVersion=7, calcRunId="R-2026Q3-01", pipelineRunId=...
        self.errors = 0

    @contextmanager
    def step(self, name: str):
        try:
            yield
        except Exception as exc:
            self.errors += 1
            self.writer("notebookErrorLog", {"runId": self.run_id, "notebook": self.notebook, "loggedAt": datetime.now(timezone.utc),
                                             "step": name, "errorType": type(exc).__name__, "message": str(exc)[:4000],
                                             "stack": traceback.format_exc()[-4000:]})
            self.finish(status="Failed")
            raise

    def finish(self, status: str = "Succeeded", rows_read: int | None = None, rows_written: int | None = None, details: str | None = None):
        self.writer("notebookRunLog", {"runId": self.run_id, "notebook": self.notebook, "startedAt": self.started,
                                       "finishedAt": datetime.now(timezone.utc), "status": status, "rowsRead": rows_read,
                                       "rowsWritten": rows_written, "details": details, **self.context})
