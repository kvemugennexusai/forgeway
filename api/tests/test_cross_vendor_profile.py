"""Tests for app.benchmark.cross_vendor.BenchmarkProfile and
load_benchmark_profile_yaml — no subprocess, no GPU, no network."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.benchmark.cross_vendor import BenchmarkProfile, ProfileError, load_benchmark_profile_yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_PROFILE_PATH = _REPO_ROOT / "benchmarks" / "profiles" / "llama-8b-cross-vendor-v0.1.yaml"


def _minimal_profile_kwargs(**overrides) -> dict:
    base = dict(
        profile_id="test-profile",
        profile_version="0.1",
        model="meta-llama/Llama-3.1-8B-Instruct",
        precision="bf16",
        input_tokens=512,
        output_tokens=128,
        concurrency=1,
        batch_behavior="static single-request batches",
        warmup_runs=1,
        measured_runs=3,
    )
    base.update(overrides)
    return base


def test_minimal_valid_profile_constructs():
    profile = BenchmarkProfile(**_minimal_profile_kwargs())
    assert profile.profile_id == "test-profile"
    assert profile.task == "text-generation"
    assert profile.runtime == "vllm"
    assert profile.tensor_parallel_degree == 1
    assert profile.quantization is None
    assert profile.env_vars == {}


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "concurrency", "tensor_parallel_degree"])
def test_rejects_non_positive_values(field):
    with pytest.raises(Exception):
        BenchmarkProfile(**_minimal_profile_kwargs(**{field: 0}))


def test_rejects_negative_warmup_runs():
    with pytest.raises(Exception):
        BenchmarkProfile(**_minimal_profile_kwargs(warmup_runs=-1))


def test_rejects_zero_measured_runs():
    with pytest.raises(Exception):
        BenchmarkProfile(**_minimal_profile_kwargs(measured_runs=0))


def test_load_benchmark_profile_yaml_raises_on_missing_file(tmp_path):
    with pytest.raises(ProfileError, match="file not found"):
        load_benchmark_profile_yaml(tmp_path / "does-not-exist.yaml")


def test_load_benchmark_profile_yaml_raises_on_invalid_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("model: [unclosed")
    with pytest.raises(ProfileError, match="invalid YAML"):
        load_benchmark_profile_yaml(path)


def test_load_benchmark_profile_yaml_raises_on_non_mapping(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ProfileError, match="must contain a YAML mapping"):
        load_benchmark_profile_yaml(path)


def test_load_benchmark_profile_yaml_raises_on_schema_violation(tmp_path):
    path = tmp_path / "missing-fields.yaml"
    path.write_text("profile_id: x\nprofile_version: '0.1'\n")
    with pytest.raises(ProfileError, match="not a valid BenchmarkProfile"):
        load_benchmark_profile_yaml(path)


def test_canonical_profile_file_loads_and_validates():
    profile = load_benchmark_profile_yaml(_CANONICAL_PROFILE_PATH)
    assert profile.profile_id == "llama-8b-cross-vendor"
    assert profile.model == "meta-llama/Llama-3.1-8B-Instruct"
    assert profile.precision == "bf16"
    assert profile.quantization is None
    assert profile.tensor_parallel_degree == 1
    assert profile.input_tokens == 512
    assert profile.output_tokens == 128
    assert profile.concurrency == 1
    assert profile.warmup_runs == 1
    assert profile.measured_runs == 3
