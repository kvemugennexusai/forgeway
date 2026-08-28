"""In-memory recommendation store. This is a fixture-driven demo — there is
no database. Records live for the life of the process and reset on restart.
"""
from __future__ import annotations

import itertools

from app.models import Recommendation


class DecisionStore:
    def __init__(self) -> None:
        self._records: dict[str, Recommendation] = {}
        self._counter = itertools.count(1)

    def next_id(self) -> str:
        return f"rec-{next(self._counter):04d}"

    def put(self, record: Recommendation) -> Recommendation:
        self._records[record.id] = record
        return record

    def get(self, record_id: str) -> Recommendation | None:
        return self._records.get(record_id)

    def latest_for_workload(self, workload_id: str) -> Recommendation | None:
        matches = [r for r in self._records.values() if r.workload_id == workload_id]
        if not matches:
            return None
        return max(matches, key=lambda r: r.generated_at)


store = DecisionStore()
