"""Single source of truth for the running Forgeway build version, so the
FastAPI app metadata and versioned schema records (e.g.
PerformanceEvidence.forgeway_version) never drift apart from each other."""
FORGEWAY_VERSION = "0.1.0"
