"""Local hardware discovery adapters — see docs/discovery.md.

Each adapter turns local system state into a `ComputeTarget`
(app.core.schemas). `app.cli.main` holds the plain, ordered list of
adapters to try; there is no plugin registry yet (see adapter.py's
docstring for why).
"""
