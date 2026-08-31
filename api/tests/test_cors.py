"""CORS must accept any localhost port, not just 3000.

`npm run dev` silently picks the next free port when 3000 is already taken
by something else (extremely common on a real developer machine) — before
this pass, that silently broke every POST-based feature (/api/analyze,
/api/import/*, scenarios) while leaving GET routes working, with the
browser only ever showing an opaque "Failed to fetch". This pins the fix
down at the actual CORS-preflight layer, not just "the route works".
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_preflight_allows_a_non_default_localhost_port():
    with TestClient(app) as client:
        r = client.options(
            "/api/import/compute-target",
            headers={
                "Origin": "http://localhost:3091",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3091"


def test_preflight_still_allows_the_documented_default_port():
    with TestClient(app) as client:
        r = client.options(
            "/api/analyze",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_preflight_rejects_a_non_localhost_origin():
    with TestClient(app) as client:
        r = client.options(
            "/api/analyze",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 400
