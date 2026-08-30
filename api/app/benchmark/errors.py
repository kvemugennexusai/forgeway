"""BenchmarkError — the one expected failure mode for app.benchmark,
mirroring app.discovery.adapter.DiscoveryError. Callers (the CLI) catch
this and report a clean one-line message; nothing in app.benchmark should
let a raw exception escape uncaught to a user running `forgeway bench`."""
from __future__ import annotations


class BenchmarkError(Exception):
    pass
