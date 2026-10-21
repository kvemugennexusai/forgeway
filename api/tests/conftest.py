"""Isolate per-machine benchmark and qualification stores for every test.

The bundled qualification fixtures remain active. Tests may override either
FORGEWAY_BENCH_DIR or FORGEWAY_QUALIFICATION_DIR with monkeypatch.setenv; their
function-level overrides take precedence over this autouse setup.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_local_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "forgeway-benchmarks-test-isolation"))
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path / "forgeway-qualifications-test-isolation"))
