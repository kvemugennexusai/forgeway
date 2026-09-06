"""The discovery adapter interface — one vendor/platform's way of turning
local system state into a ComputeTarget.

Deliberately minimal: no plugin registry, no auto-discovery of adapter
classes, no configuration system. `app/cli/main.py` just holds a plain list
of adapter instances to try, in order. Add a new vendor by writing a new
class here and adding one line to that list — nothing else changes.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Literal, Optional

from pydantic import BaseModel, Field

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


#: Upper bound on how long a single adapter's discover() may run before
#: discover_all() gives up on it and moves on. Real adapters (nvidia.py,
#: rocm.py) already bound their own subprocess calls at 5s; this is a
#: backstop against an adapter that doesn't — e.g. one that blocks on I/O
#: with no internal timeout of its own.
DEFAULT_ADAPTER_TIMEOUT_S = 30.0

#: Which phase of one adapter's run produced an AdapterError — surfaced so
#: a caller/reader can tell "this adapter's tooling isn't even present"
#: (is_available, which per the docstring above must never raise — this is
#: a defensive catch of a contract violation, not an expected path) apart
#: from "this adapter's tooling is present but discovery itself failed"
#: (discover, which legitimately can raise DiscoveryError or anything
#: else).
AdapterStage = Literal["is_available", "discover"]


class AdapterError(BaseModel):
    """One adapter's failure, recorded rather than swallowed. `error_type`
    is the exception class name (e.g. "DiscoveryError", "TimeoutError",
    "RuntimeError") — enough to tell a clean, expected failure apart from
    an adapter bug without parsing `message` text."""

    adapter: str
    stage: AdapterStage
    error_type: str
    message: str


class DiscoveryResult(BaseModel):
    """The outcome of running every registered adapter: whatever targets
    were actually found, plus every failure along the way. A caller that
    only wants "the first target, or a clean error" (today's
    `app.cli.main.run_discovery`) is built on top of this, not a
    replacement for it."""

    targets: list[ComputeTarget] = Field(default_factory=list)
    errors: list[AdapterError] = Field(default_factory=list)


def _run_discover_with_timeout(
    adapter: DiscoveryAdapter, timeout_s: float
) -> tuple[Optional[ComputeTarget], Optional[BaseException]]:
    """Runs adapter.discover() on a daemon thread and waits up to
    timeout_s. A plain ThreadPoolExecutor is deliberately not used here:
    its worker threads are non-daemon, so a hung adapter would keep the
    whole process alive waiting to join that thread even after we've given
    up on it — exactly the hang this function exists to bound. A daemon
    thread is abandoned instead: it may keep running in the background,
    but it never blocks process exit."""
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = adapter.discover()
        except BaseException as e:  # noqa: BLE001 - deliberately broad, see discover_all
            box["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return None, TimeoutError(f"did not complete within {timeout_s:.0f}s")
    if "error" in box:
        return None, box["error"]  # type: ignore[return-value]
    return box.get("value"), None  # type: ignore[return-value]


def discover_all(
    adapters: list[DiscoveryAdapter], *, timeout_s: float = DEFAULT_ADAPTER_TIMEOUT_S
) -> DiscoveryResult:
    """Runs every adapter independently and collects both the targets that
    were found and every failure along the way. One adapter raising,
    hanging, or returning something that isn't a ComputeTarget never
    prevents the others from running or being reported — see WP1 in the
    discovery/adapter cleanup notes.

    Never raises: an adapter's own bugs (is_available() raising against its
    documented contract, discover() raising, hanging past timeout_s, or
    returning a non-ComputeTarget) all become an AdapterError instead."""
    targets: list[ComputeTarget] = []
    errors: list[AdapterError] = []

    for adapter in adapters:
        try:
            available = adapter.is_available()
        except Exception as e:  # noqa: BLE001 - is_available() must never raise; caught defensively anyway
            errors.append(
                AdapterError(
                    adapter=adapter.name, stage="is_available", error_type=type(e).__name__, message=str(e)
                )
            )
            continue
        if not available:
            continue

        target, error = _run_discover_with_timeout(adapter, timeout_s)
        if error is not None:
            errors.append(
                AdapterError(
                    adapter=adapter.name, stage="discover", error_type=type(error).__name__, message=str(error)
                )
            )
            continue
        if not isinstance(target, ComputeTarget):
            errors.append(
                AdapterError(
                    adapter=adapter.name,
                    stage="discover",
                    error_type="TypeError",
                    message=f"expected a ComputeTarget, got {type(target).__name__}",
                )
            )
            continue
        targets.append(target)

    return DiscoveryResult(targets=targets, errors=errors)
