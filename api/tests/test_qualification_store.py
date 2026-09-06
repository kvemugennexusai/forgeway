"""Tests for app.qualification.store — real filesystem I/O against a
tmp_path (local layer, via FORGEWAY_QUALIFICATION_DIR) and a monkeypatched
fixture path (bundled layer) — WP2 of Phase 2's qualification records
work. No real hardware or subprocess involved.
"""
from __future__ import annotations

import json
from datetime import date

from app.core.schemas.v0_1.qualification import QualificationRecord, QualificationSubject
from app.qualification import store


def _subject(**overrides) -> QualificationSubject:
    base = dict(
        vendor="nvidia",
        hardware_model="H100 80GB HBM3",
        architecture="hopper",
        runtime="vllm",
        model="meta-llama/Llama-3.1-8B-Instruct",
        precision="bf16",
        workload_class="realtime-inference",
    )
    base.update(overrides)
    return QualificationSubject(**base)


def _record(subject: QualificationSubject, **overrides) -> QualificationRecord:
    base = dict(state="smoke_tested", source="forgeway qualify", environment="test")
    base.update(overrides)
    return QualificationRecord.for_subject(subject, **base)


# --------------------------------------------------------------------------
# qualifications_dir()
# --------------------------------------------------------------------------


def test_qualifications_dir_respects_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path / "custom"))
    assert store.qualifications_dir() == tmp_path / "custom"


def test_qualifications_dir_defaults_to_home_dot_forgeway(monkeypatch):
    monkeypatch.delenv("FORGEWAY_QUALIFICATION_DIR", raising=False)
    assert str(store.qualifications_dir()).endswith(".forgeway/qualifications")


# --------------------------------------------------------------------------
# save_qualification() / local lookup
# --------------------------------------------------------------------------


def test_save_and_get_round_trips_a_local_record(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    subject = _subject()
    record = _record(subject)

    path = store.save_qualification(record)

    assert path == tmp_path / f"{record.id}.json"
    assert store.get_qualification(subject) == record


def test_get_qualification_returns_none_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    assert store.get_qualification(_subject()) is None


def test_saving_the_same_subject_again_overwrites_not_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    subject = _subject()
    store.save_qualification(_record(subject, state="unknown", source="s1"))
    store.save_qualification(_record(subject, state="smoke_tested", source="s2"))

    assert len(list(tmp_path.glob("*.json"))) == 1
    assert store.get_qualification(subject).state == "smoke_tested"


def test_local_records_skip_unparseable_files_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    store.save_qualification(_record(_subject()))
    (tmp_path / "not-a-record.json").write_text("{not valid json")

    assert len(store.list_qualifications()) == 1


# --------------------------------------------------------------------------
# Fixture layer + local-overrides-fixture merge
# --------------------------------------------------------------------------


def test_get_qualification_falls_back_to_the_fixture_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    subject = _subject()
    fixture_record = _record(subject, state="unknown", source="fixture baseline")
    fixture_path = tmp_path / "fixture-qualifications.json"
    fixture_path.write_text(json.dumps([json.loads(fixture_record.model_dump_json())]))
    monkeypatch.setattr(store, "_FIXTURES_PATH", fixture_path)

    assert store.get_qualification(subject) == fixture_record


def test_local_record_overrides_the_fixture_for_the_same_subject(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path / "local"))
    subject = _subject()
    fixture_record = _record(subject, state="unknown", source="fixture baseline")
    fixture_path = tmp_path / "fixture-qualifications.json"
    fixture_path.write_text(json.dumps([json.loads(fixture_record.model_dump_json())]))
    monkeypatch.setattr(store, "_FIXTURES_PATH", fixture_path)

    local_record = _record(subject, state="smoke_tested", source="real local check")
    store.save_qualification(local_record)

    assert store.get_qualification(subject) == local_record
    assert store.list_qualifications() == [local_record]


def test_list_qualifications_merges_fixture_and_local_when_subjects_differ(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path / "local"))
    fixture_record = _record(_subject(vendor="aws", hardware_model="Trainium2"), state="unknown", source="fixture")
    fixture_path = tmp_path / "fixture-qualifications.json"
    fixture_path.write_text(json.dumps([json.loads(fixture_record.model_dump_json())]))
    monkeypatch.setattr(store, "_FIXTURES_PATH", fixture_path)

    local_record = _record(_subject(vendor="nvidia", hardware_model="H100"))
    store.save_qualification(local_record)

    ids = {r.id for r in store.list_qualifications()}
    assert ids == {fixture_record.id, local_record.id}


def test_missing_fixture_file_is_treated_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    monkeypatch.setattr(store, "_FIXTURES_PATH", tmp_path / "does-not-exist.json")
    assert store.list_qualifications() == []


# --------------------------------------------------------------------------
# is_stale()
# --------------------------------------------------------------------------


def test_is_stale_is_false_when_review_date_is_none():
    record = _record(_subject())
    assert store.is_stale(record) is False


def test_is_stale_is_false_before_the_review_date():
    record = _record(_subject(), review_date=date(2030, 1, 1))
    assert store.is_stale(record, as_of=date(2029, 1, 1)) is False


def test_is_stale_is_true_after_the_review_date():
    record = _record(_subject(), review_date=date(2020, 1, 1))
    assert store.is_stale(record, as_of=date(2025, 1, 1)) is True
