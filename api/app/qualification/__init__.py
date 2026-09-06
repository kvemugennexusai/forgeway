"""Qualification records — sourced, dated, evidence-linked facts about
whether one specific hardware+runtime+model+precision+config+workload/SLO
combination actually works. See docs/qualification.md.

Sibling package to app.discovery and app.benchmark: app.qualification.store
holds the databank (a bundled fixture layer + a local directory of real
checks, merged), and app.qualification.checker runs the staged pipeline
(runtime present -> device reachable -> config supported -> smoke test
passed) that produces new records.
"""
