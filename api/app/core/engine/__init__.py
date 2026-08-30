"""Forgeway core engine — pure functions over app.core.schemas.

feasibility.py  the compatibility/feasibility engine (hard constraints)
scoring.py      prediction retrieval, replica sizing, and the SLO gate
ranking.py      objective-weighted normalization/ranking across candidates

No filesystem, network, or product-specific (UI/narrative) concerns live
here — a product wraps these with its own data source and presentation.
"""
