"""Loads a user-supplied YAML file into a validated Forgeway schema object
— the `forgeway analyze` entry point (docs/analyze.md is folded into
README.md's end-to-end CLI flow section). The only place this CLI reads
an arbitrary, user-specified file path (as opposed to app/data/loader.py's
fixed fixture files or app/benchmark/store.py's results directory).

AnalyzeError is the one expected failure mode here — a missing file, a
YAML syntax error, or a value that doesn't validate against the schema —
mirroring DiscoveryError and BenchmarkError. Callers (the CLI) catch this
and report a clean message; nothing here lets a raw exception or a
pydantic traceback escape to a user running the command.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.schemas import EnterprisePolicy, Workload


class AnalyzeError(Exception):
    pass


def _load_yaml_dict(path: Path) -> dict:
    if not path.exists():
        raise AnalyzeError(f"file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise AnalyzeError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise AnalyzeError(f"{path} must contain a YAML mapping (got {type(raw).__name__})")
    return raw


def load_workload_yaml(path: Path) -> Workload:
    """Loads and validates an AIWorkload from a YAML file. Field names and
    structure exactly match the AIWorkload schema (docs/schemas.md) — see
    examples/workload.yaml for a complete, working example."""
    raw = _load_yaml_dict(path)
    try:
        return Workload.model_validate(raw)
    except ValidationError as e:
        raise AnalyzeError(f"{path} is not a valid AIWorkload:\n{e}") from e


def load_policy_yaml(path: Path) -> EnterprisePolicy:
    """Loads and validates an EnterprisePolicy from a YAML file, for
    `forgeway analyze --policy <file>` to override a workload's own
    embedded policy for one run — see examples/policy.yaml."""
    raw = _load_yaml_dict(path)
    try:
        return EnterprisePolicy.model_validate(raw)
    except ValidationError as e:
        raise AnalyzeError(f"{path} is not a valid EnterprisePolicy:\n{e}") from e
