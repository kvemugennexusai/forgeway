"""Forgeway core: the reusable, product-agnostic workload-intelligence layer.

Everything under `app.core` is designed to be lifted out of this demo and
reused by any caller that needs to reason about heterogeneous AI compute —
a different UI, a CLI, a notebook, a scheduler. Nothing in here knows about
this product's HTTP routes, its in-memory store, its six demo scenarios, or
how its dashboard narrates a recommendation. See docs/open-source-architecture.md
for the public-vs-product boundary this package draws.

`app.core.schemas`  typed contracts: compute targets, workloads, evidence
                    (Metric/provenance), and engine output shapes.
`app.core.engine`   pure functions over those contracts: hard-compatibility
                    checks, prediction retrieval/sizing/SLO checks, and
                    objective-weighted ranking. No filesystem or network
                    access anywhere in this package — callers supply typed
                    objects however they obtain them (fixtures today; a
                    discovery adapter or benchmark run tomorrow).
"""
