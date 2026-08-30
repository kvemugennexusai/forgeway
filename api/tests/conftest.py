"""Shared, autouse test fixtures.

isolate_benchmark_store is the important one: without it, every test that
calls app.engine.decision.run_decision() (directly or indirectly) reads
the real ~/.forgeway/benchmarks directory via app.benchmark.store.list_runs(),
since decision.py never scopes that path itself. On a machine with no
real benchmark runs saved that's silently harmless; on a machine (or CI
runner) where a real `forgeway bench` run has ever been saved, every
decision-engine test — not just the ones about evidence — would start
reading that ambient state and could produce different, unexplained
results that have nothing to do with the code under test. This fixture
makes every test's benchmark store an empty, unique tmp_path by default,
regardless of what's on the machine actually running the suite.

Tests that specifically exercise the benchmark store (e.g.
tests/test_benchmark_store.py) still monkeypatch FORGEWAY_BENCH_DIR
themselves where they need a specific location — that's fine, this
fixture and a test's own monkeypatch.setenv share the same underlying
monkeypatch instance per test, so the test's own call simply wins.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_benchmark_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "forgeway-benchmarks-test-isolation"))
