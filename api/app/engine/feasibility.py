"""Hard compatibility checks — the feasible-set filter.

A target is feasible only if every check here passes. Order matters only for
readability; all checks run and are reported, so the UI can show the full
checklist rather than just the first failure. This mirrors the "independent
axes, never derive one from another" discipline: policy, memory, precision
and workload-class qualification are unrelated facts and must fail with
their own reason, never a borrowed one.
"""
from __future__ import annotations

import re

from app.models import ComputeTarget, FeasibilityCheck, Workload


def _location_tokens(location: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-zA-Z0-9\-]+", location.lower()) if tok}


def evaluate_feasibility(workload: Workload, target: ComputeTarget) -> list[FeasibilityCheck]:
    checks: list[FeasibilityCheck] = []

    vendor_denied = target.vendor in workload.policy.denied_vendors
    vendor_allowed = (not workload.policy.allowed_vendors) or (
        target.vendor in workload.policy.allowed_vendors
    )
    checks.append(
        FeasibilityCheck(
            name="policy: vendor allowed",
            passed=vendor_allowed and not vendor_denied,
            detail=(
                f"vendor '{target.vendor}' is within the workload's allowed-vendor policy"
                if vendor_allowed and not vendor_denied
                else f"vendor '{target.vendor}' is excluded by workload policy"
            ),
        )
    )

    region_tokens = _location_tokens(target.location)
    region_ok = any(r.lower() in region_tokens for r in workload.policy.allowed_regions)
    checks.append(
        FeasibilityCheck(
            name="policy: region/residency allowed",
            passed=region_ok,
            detail=(
                f"target location '{target.location}' matches an allowed region"
                if region_ok
                else f"target location '{target.location}' is outside the workload's allowed regions "
                f"({', '.join(workload.policy.allowed_regions)})"
            ),
        )
    )

    required_memory_gb = workload.weights_footprint_gb + workload.kv_cache_overhead_gb
    memory_ok = target.memory_gb_per_device >= required_memory_gb
    checks.append(
        FeasibilityCheck(
            name="memory: single-device footprint fits",
            passed=memory_ok,
            detail=(
                f"{required_memory_gb:.0f} GB required (weights + KV cache) fits in "
                f"{target.memory_gb_per_device:.0f} GB/device"
                if memory_ok
                else f"{required_memory_gb:.0f} GB required (weights + KV cache) exceeds "
                f"{target.memory_gb_per_device:.0f} GB/device; tensor-parallel split across devices "
                "is not modeled for this target profile"
            ),
        )
    )

    precision_ok = workload.precision in target.supported_precisions
    checks.append(
        FeasibilityCheck(
            name="architecture: precision/runtime compatible",
            passed=precision_ok,
            detail=(
                f"'{workload.precision}' is a supported precision on {target.model}"
                if precision_ok
                else f"'{workload.precision}' is not among the supported precisions on {target.model} "
                f"({', '.join(target.supported_precisions)})"
            ),
        )
    )

    unsupported = next(
        (u for u in target.unsupported_workload_classes if u.workload_class == workload.workload_class),
        None,
    )
    checks.append(
        FeasibilityCheck(
            name="software: workload class qualified",
            passed=unsupported is None,
            detail=(
                f"'{workload.workload_class}' is a qualified workload class on {target.model}"
                if unsupported is None
                else unsupported.reason
            ),
        )
    )

    checks.append(
        FeasibilityCheck(
            name="capacity: target is online",
            passed=target.status == "healthy",
            detail=(
                f"{target.model} reports healthy status"
                if target.status == "healthy"
                else f"{target.model} reports status '{target.status}'"
            ),
        )
    )

    return checks
