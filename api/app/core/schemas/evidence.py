"""The evidence primitive — the one shape every number in the engine is
reported through.

Every metric carries what it is, how sure we are, where it came from, and
the range it could plausibly fall in (when one is known). A candidate is
never allowed to present a MODELED number as if it were MEASURED — this is
the type that makes that distinction impossible to drop on the way to a
caller.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Provenance = Literal["MEASURED", "PUBLISHED", "MODELED"]


class Metric(BaseModel):
    value: float
    confidence: float = Field(ge=0, le=100)
    provenance: Provenance
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    source: str = ""
