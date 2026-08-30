"""The discovery adapter interface — one vendor/platform's way of turning
local system state into a ComputeTarget.

Deliberately minimal: no plugin registry, no auto-discovery of adapter
classes, no configuration system. `app/cli/main.py` just holds a plain list
of adapter instances to try, in order. Add a new vendor by writing a new
class here and adding one line to that list — nothing else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.schemas import ComputeTarget


class DiscoveryError(Exception):
    """Raised when an adapter's tooling is present but discovery still
    couldn't produce a ComputeTarget (a failed command, unparseable output,
    zero devices reported). Callers are expected to catch this and report
    it as a clean one-line message — never let it surface as a raw
    traceback."""


class DiscoveryAdapter(ABC):
    """One vendor's local hardware discovery. Each adapter owns both
    detection (is its tooling present at all?) and parsing (turn that
    tooling's output into a typed ComputeTarget)."""

    #: short, human-readable name for CLI messages, e.g. "NVIDIA"
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap, side-effect-free check: does this machine plausibly have
        this adapter's tooling? Must never raise — on any doubt, return
        False so the CLI can try the next adapter or report nothing found."""

    @abstractmethod
    def discover(self) -> ComputeTarget:
        """Run discovery and return one ComputeTarget describing this
        machine's hardware. Only called after is_available() returned
        True. Raises DiscoveryError if the tooling turns out to fail once
        actually invoked (e.g. a transient driver error)."""
