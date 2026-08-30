"""Tests for app.benchmark.parser — pure JSON-in, typed-result-out, no
mocking needed at all. These are static JSON fixtures standing in for
`vllm bench latency --output-json`'s output.
"""
from __future__ import annotations

import pytest

from app.benchmark.errors import BenchmarkError
from app.benchmark.parser import parse_vllm_latency_output


def test_parses_avg_latency_and_percentiles():
    raw = {"avg_latency": 1.234, "percentiles": {"50": 1.20, "99": 1.35}}
    result = parse_vllm_latency_output(raw)
    assert result.avg_latency_s == 1.234
    assert result.percentiles_s == {"50": 1.20, "99": 1.35}


def test_parses_avg_latency_with_no_percentiles():
    raw = {"avg_latency": 0.842}
    result = parse_vllm_latency_output(raw)
    assert result.avg_latency_s == 0.842
    assert result.percentiles_s == {}


def test_falls_back_to_alternate_avg_latency_key_names():
    result = parse_vllm_latency_output({"average_latency": 2.0})
    assert result.avg_latency_s == 2.0

    result = parse_vllm_latency_output({"avg_latency_s": 3.0})
    assert result.avg_latency_s == 3.0


def test_ignores_non_numeric_percentile_values():
    raw = {"avg_latency": 1.0, "percentiles": {"50": 1.0, "99": "not-a-number"}}
    result = parse_vllm_latency_output(raw)
    assert result.percentiles_s == {"50": 1.0}


def test_raises_benchmark_error_when_avg_latency_is_entirely_missing():
    with pytest.raises(BenchmarkError, match="average-latency"):
        parse_vllm_latency_output({"some_other_field": 42})


def test_raises_benchmark_error_when_avg_latency_is_not_numeric():
    with pytest.raises(BenchmarkError):
        parse_vllm_latency_output({"avg_latency": "oops"})
