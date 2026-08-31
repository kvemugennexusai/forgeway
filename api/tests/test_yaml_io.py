"""Tests for app.cli.yaml_io — loading and validating AIWorkload /
EnterprisePolicy YAML files, including error handling.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.yaml_io import AnalyzeError, load_policy_yaml, load_workload_yaml

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def test_loads_the_real_example_workload():
    workload = load_workload_yaml(_EXAMPLES_DIR / "workload.yaml")
    assert workload.id == "wl-llama70b-rt"
    assert workload.schema_version == "forgeway/v0.1"


def test_loads_the_real_example_policy():
    policy = load_policy_yaml(_EXAMPLES_DIR / "policy.yaml")
    assert policy.allowed_vendors == ["nvidia"]
    assert policy.denied_vendors == ["amd"]


def test_raises_analyze_error_when_workload_file_missing(tmp_path):
    with pytest.raises(AnalyzeError, match="file not found"):
        load_workload_yaml(tmp_path / "does-not-exist.yaml")


def test_raises_analyze_error_on_invalid_yaml_syntax(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: [unterminated\n  - broken")
    with pytest.raises(AnalyzeError, match="invalid YAML"):
        load_workload_yaml(bad)


def test_raises_analyze_error_when_yaml_is_not_a_mapping(tmp_path):
    not_a_mapping = tmp_path / "list.yaml"
    not_a_mapping.write_text("- one\n- two\n")
    with pytest.raises(AnalyzeError, match="mapping"):
        load_workload_yaml(not_a_mapping)


def test_raises_analyze_error_when_workload_fails_schema_validation(tmp_path):
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("id: wl-incomplete\n")
    with pytest.raises(AnalyzeError, match="not a valid AIWorkload"):
        load_workload_yaml(incomplete)


def test_raises_analyze_error_when_policy_fails_schema_validation(tmp_path):
    incomplete = tmp_path / "bad-policy.yaml"
    incomplete.write_text("allowed_vendors: [nvidia]\n")  # missing allowed_regions/budget_ceiling_per_hr
    with pytest.raises(AnalyzeError, match="not a valid EnterprisePolicy"):
        load_policy_yaml(incomplete)
