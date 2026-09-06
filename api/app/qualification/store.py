"""Persists and looks up QualificationRecords — a "databank" merged from
two layers: a bundled fixture (api/app/fixtures/qualifications.json,
demo-shipped, mirrors app.data.loader's compute-target fixture) and a
local directory of real checks (~/.forgeway/qualifications by default,
override via FORGEWAY_QUALIFICATION_DIR — same convention as
app.benchmark.store's FORGEWAY_BENCH_DIR). A local record for a subject
overrides the fixture's for that same subject.

This is a current-state store, not an audit log: saving a record for a
subject that's already there overwrites it (the id is deterministic from
the subject — app.core.schemas.v0_1.qualification.QualificationSubject.
subject_key()) — the same philosophy as `forgeway discover` overwriting
the previous view of "this machine now" rather than appending to a
history. If real auditability matters later, that's a versioned-store
redesign, not this one.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from app.core.schemas.v0_1.qualification import QualificationRecord, QualificationSubject

#: Not lru_cache'd (unlike app.data.loader's fixture loaders): this file is
#: small, read infrequently (once per `forgeway qualify`/`analyze` run, not
#: in a hot per-candidate loop), and tests need to point it at a temporary
#: fixture file without a stale cache surviving between them.
_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "qualifications.json"


def qualifications_dir() -> Path:
    """~/.forgeway/qualifications by default; override with
    FORGEWAY_QUALIFICATION_DIR (used by tests to isolate records in a tmp
    directory, mirrors app.benchmark.store.results_dir())."""
    override = os.environ.get("FORGEWAY_QUALIFICATION_DIR")
    return Path(override) if override else Path.home() / ".forgeway" / "qualifications"


def _load_fixture_records() -> dict[str, QualificationRecord]:
    if not _FIXTURES_PATH.exists():
        return {}
    raw = json.loads(_FIXTURES_PATH.read_text())
    return {item["id"]: QualificationRecord.model_validate(item) for item in raw}


def _load_local_records() -> dict[str, QualificationRecord]:
    """A file that fails to parse as a QualificationRecord (foreign JSON,
    a future/incompatible schema version) is skipped rather than crashing
    every caller — same convention as app.benchmark.store.list_runs()."""
    directory = qualifications_dir()
    if not directory.exists():
        return {}
    records: dict[str, QualificationRecord] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            record = QualificationRecord.model_validate_json(path.read_text())
        except (ValueError, OSError):
            continue
        records[record.id] = record
    return records


def save_qualification(record: QualificationRecord) -> Path:
    """Writes <record.id>.json into the local directory, overwriting any
    existing file for the same id (i.e. the same subject) — see module
    docstring on why this is current-state, not an audit log."""
    directory = qualifications_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.id}.json"
    path.write_text(record.model_dump_json(indent=2) + "\n")
    return path


def get_qualification(subject: QualificationSubject) -> Optional[QualificationRecord]:
    """The databank lookup: "evaluate if something is already in the
    databank." A local, real check for this exact subject takes
    precedence over the bundled fixture's baseline for the same subject;
    falls back to the fixture when no local record exists; returns None
    when neither has one — "nobody has checked" is a valid, common,
    non-error outcome, not something this function raises for."""
    record_id = f"qual-{subject.subject_key()}"
    local = _load_local_records()
    if record_id in local:
        return local[record_id]
    return _load_fixture_records().get(record_id)


def list_qualifications() -> list[QualificationRecord]:
    """Every record in the databank, fixture merged with local (local
    overriding the fixture on an id collision, same rule as
    get_qualification())."""
    merged = dict(_load_fixture_records())
    merged.update(_load_local_records())
    return list(merged.values())


def is_stale(record: QualificationRecord, as_of: Optional[date] = None) -> bool:
    """A record is stale once its review_date has passed. Takes an
    explicit `as_of` (default: today) rather than living on the model
    itself as a computed field — staleness is a judgment made at read
    time against the calendar, not a fact about the record's own data,
    and callers/tests need to control "today" without depending on the
    wall clock. `review_date=None` (no expiry tracked) is never stale."""
    if record.review_date is None:
        return False
    return record.review_date < (as_of if as_of is not None else date.today())
