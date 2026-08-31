"""CORS must accept any localhost port, not just 3000, and any private-LAN
origin, not just the host machine itself.

`npm run dev` silently picks the next free port when 3000 is already taken
by something else (extremely common on a real developer machine) — before
this pass, that silently broke every POST-based feature (/api/analyze,
/api/import/*, scenarios) while leaving GET routes working, with the
browser only ever showing an opaque "Failed to fetch". Testing the web demo
from another device on the same LAN (docs/architecture.md) hits the same
failure mode from a different angle: that device's origin is a private IP,
never `localhost`. This pins both fixes down at the actual CORS-preflight
layer, not just "the route works" — including the boundary: a public,
internet-routable origin must still be rejected.
"""
from __future__ import annotations

import pytest
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


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.86.39:3000", # a real LAN IP seen during this feature's own testing
        "http://192.168.0.1:3091",
        "http://10.0.0.5:3000",
        "http://172.16.0.1:3000",
        "http://172.31.255.255:3000",
    ],
)
def test_preflight_allows_a_private_lan_origin(origin):
    with TestClient(app) as client:
        r = client.options(
            "/api/analyze",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin


def test_preflight_rejects_a_public_internet_origin():
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


@pytest.mark.parametrize(
    "origin",
    [
        "http://172.15.0.1:3000",  # just outside the 172.16-31 private range
        "http://172.32.0.1:3000",  # just outside on the other side
        "https://192.168.86.39:3000",  # https, not http — never matched
    ],
)
def test_preflight_rejects_addresses_that_look_private_but_arent(origin):
    """Guards the regex's actual boundaries, not just the obviously-public
    case above — a public IP one digit away from a private range, or the
    right IP on the wrong scheme, must still be rejected."""
    with TestClient(app) as client:
        r = client.options(
            "/api/analyze",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 400
