"""Router-level tests for the "Import benchmark result" feature
(docs/importing-results.md): the two stateless validation endpoints
(`/api/import/performance-evidence`, `/api/import/compute-target`) and
`/api/analyze`'s handling of `imported_targets`/`imported_evidence`.

Uses FastAPI's TestClient directly — these exercise the real HTTP request/
response cycle, including Pydantic's automatic validation-error responses,
which is the actual mechanism docs/importing-results.md relies on for
"clear errors for invalid schema / unsupported schema version / malformed
evidence / missing required fields" (no hand-rolled validation to test in
isolation — there isn't any).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _valid_evidence(**overrides) -> dict:
    base = {
        "compute_target_id": "local-nvidia-test-host",
        "workload_id": "wl-llama70b-rt",
        "metrics": {
            "p99_latency_ms_per_replica": {
                "value": 200, "confidence": 95, "provenance": "MEASURED", "source": "my bench"
            },
            "throughput_tokens_per_s_per_replica": {
                "value": 2000, "confidence": 95, "provenance": "MEASURED", "source": "my bench"
            },
        },
        "provenance": "MEASURED",
        "confidence": 95,
        "source": "my bench",
    }
    base.update(overrides)
    return base


def _valid_target(**overrides) -> dict:
    base = {
        "id": "local-nvidia-test-host",
        "vendor": "nvidia",
        "model": "RTX 6000 Ada 96GB",
        "tier": "lab",
        "location": "us-east-1 (cloud)",
        "architecture": "ada-lovelace",
        "memory_gb_per_device": 96,
        "interconnect": "not probed",
        "supported_precisions": ["fp16", "fp8"],
        "capacity_units_total": 2,
        "capacity_units_allocated": 0,
        "price_per_hr_per_unit": {"value": 1.50, "confidence": 85, "provenance": "PUBLISHED", "source": "list price"},
        "status": "healthy",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# /api/import/performance-evidence
# --------------------------------------------------------------------------


def test_validate_performance_evidence_accepts_a_valid_record():
    with TestClient(app) as client:
        r = client.post("/api/import/performance-evidence", json=_valid_evidence())
    assert r.status_code == 200
    assert r.json()["schema_version"] == "forgeway/v0.1"


def test_validate_performance_evidence_rejects_unsupported_schema_version():
    with TestClient(app) as client:
        r = client.post(
            "/api/import/performance-evidence", json=_valid_evidence(schema_version="forgeway/v0.2")
        )
    assert r.status_code == 422
    assert any("schema_version" in err["loc"] for err in r.json()["detail"])


def test_validate_performance_evidence_rejects_missing_required_fields():
    with TestClient(app) as client:
        r = client.post("/api/import/performance-evidence", json={"compute_target_id": "x"})
    assert r.status_code == 422
    missing_fields = {err["loc"][-1] for err in r.json()["detail"] if err["type"] == "missing"}
    assert {"workload_id", "provenance", "confidence"}.issubset(missing_fields)


def test_validate_performance_evidence_rejects_malformed_json_body():
    with TestClient(app) as client:
        r = client.post(
            "/api/import/performance-evidence",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "json_invalid"


# --------------------------------------------------------------------------
# /api/import/compute-target
# --------------------------------------------------------------------------


def test_validate_compute_target_accepts_a_valid_record():
    with TestClient(app) as client:
        r = client.post("/api/import/compute-target", json=_valid_target())
    assert r.status_code == 200
    assert r.json()["accelerator_count"] == 2  # computed field present, proves full validation ran


def test_validate_compute_target_rejects_missing_required_fields():
    with TestClient(app) as client:
        r = client.post("/api/import/compute-target", json={"id": "x"})
    assert r.status_code == 422
    missing_fields = {err["loc"][-1] for err in r.json()["detail"] if err["type"] == "missing"}
    assert "memory_gb_per_device" in missing_fields
    assert "price_per_hr_per_unit" in missing_fields


# --------------------------------------------------------------------------
# /api/analyze — imported_targets / imported_evidence
# --------------------------------------------------------------------------


def test_analyze_rejects_an_imported_target_colliding_with_a_reference_id():
    colliding = _valid_target(id="nvidia-h100-dc")
    with TestClient(app) as client:
        r = client.post(
            "/api/analyze", json={"workload_id": "wl-llama70b-rt", "imported_targets": [colliding]}
        )
    assert r.status_code == 400
    assert "nvidia-h100-dc" in r.json()["detail"]


def test_analyze_includes_an_imported_target_as_an_evaluated_candidate():
    with TestClient(app) as client:
        r = client.post(
            "/api/analyze",
            json={
                "workload_id": "wl-llama70b-rt",
                "imported_targets": [_valid_target()],
                "imported_evidence": [_valid_evidence()],
            },
        )
    assert r.status_code == 200
    candidate_ids = {c["target_id"] for c in r.json()["candidates"]}
    assert "local-nvidia-test-host" in candidate_ids


def test_analyze_can_recommend_an_imported_target_when_it_genuinely_qualifies():
    """The full positive path: a properly-specced, honestly-evidenced
    imported target can win the recommendation outright, exactly like any
    reference target — no special-casing, same 11-step pipeline."""
    with TestClient(app) as client:
        r = client.post(
            "/api/analyze",
            json={
                "workload_id": "wl-llama70b-rt",
                "imported_targets": [_valid_target()],
                "imported_evidence": [_valid_evidence()],
            },
        )
    d = r.json()
    assert d["recommended_target_id"] == "local-nvidia-test-host"
    winner = next(c for c in d["candidates"] if c["target_id"] == "local-nvidia-test-host")
    assert winner["status"] == "recommended"
    assert winner["raw_prediction"]["throughput_tokens_per_s"]["provenance"] == "MEASURED"


def test_analyze_rejects_imported_evidence_targeting_a_reference_id_it_did_not_import():
    """The exact exploit this check exists to close: imported_evidence
    naming an existing reference-catalog compute_target_id (nvidia-h100-dc)
    — with no matching entry in imported_targets — must never be gathered
    as a scoring candidate for that reference target. Without this check,
    fabricated MEASURED evidence at high confidence would silently outrank
    and replace the reference target's real fixture evidence via ordinary
    provenance/confidence tie-breaking, in direct violation of "do not
    merge imported data silently with demo/reference fixtures"
    (docs/importing-results.md)."""
    fabricated = _valid_evidence(
        compute_target_id="nvidia-h100-dc",
        metrics={
            "p99_latency_ms_per_replica": {
                "value": 1, "confidence": 99, "provenance": "MEASURED", "source": "fabricated"
            },
            "throughput_tokens_per_s_per_replica": {
                "value": 999999, "confidence": 99, "provenance": "MEASURED", "source": "fabricated"
            },
        },
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/analyze", json={"workload_id": "wl-llama70b-rt", "imported_evidence": [fabricated]}
        )
    assert r.status_code == 400
    assert "nvidia-h100-dc" in r.json()["detail"]


def test_analyze_rejects_an_underspecced_imported_target_honestly():
    """An imported target that doesn't actually fit the workload (not
    enough memory, wrong region/precision) must be rejected with real,
    specific reasons — never silently excluded or silently accepted."""
    underspecced = _valid_target(
        model="RTX 4090", location="local (my-machine)", memory_gb_per_device=24,
        supported_precisions=["fp16"],
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/analyze",
            json={
                "workload_id": "wl-llama70b-rt",
                "imported_targets": [underspecced],
                "imported_evidence": [_valid_evidence()],
            },
        )
    d = r.json()
    candidate = next(c for c in d["candidates"] if c["target_id"] == "local-nvidia-test-host")
    assert candidate["status"] == "rejected"
    assert candidate["feasible"] is False
    assert any("GB" in reason for reason in candidate["rejection_reasons"])
