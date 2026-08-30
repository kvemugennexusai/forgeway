"""The `forgeway` CLI. Currently one subcommand: `forgeway discover`.

Installed as a console script via api/pyproject.toml
(`pip install -e api/`, or `python -m app.cli.main discover` without
installing). See docs/discovery.md.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from app.core.schemas import ComputeTarget
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError
from app.discovery.nvidia import NvidiaDiscoveryAdapter

#: Adapters to try, in order. Adding a vendor is adding one line here plus
#: one new adapter class — see app/discovery/adapter.py.
ADAPTERS: list[DiscoveryAdapter] = [NvidiaDiscoveryAdapter()]


def run_discovery(adapters: Optional[list[DiscoveryAdapter]] = None) -> ComputeTarget:
    """Tries each adapter's is_available() in order and returns the first
    one's discover() result. Raises DiscoveryError, with a message safe to
    print directly to a user, if none of this machine's tooling is
    supported yet. Defaults to the module-level ADAPTERS list, resolved at
    call time (not at import time) so tests can reassign
    app.cli.main.ADAPTERS and have this function pick up the change."""
    if adapters is None:
        adapters = ADAPTERS
    for adapter in adapters:
        if adapter.is_available():
            return adapter.discover()
    names = ", ".join(a.name for a in adapters) or "(none configured)"
    raise DiscoveryError(
        "No supported accelerator was detected on this machine. "
        f"Checked: {names}. See docs/discovery.md for what's supported."
    )


def format_human(target: ComputeTarget) -> str:
    lines = [
        "Forgeway discovery: local compute target",
        "",
        f"  Vendor / model   {target.vendor} — {target.model}",
        f"  Devices          {target.accelerator_count}",
        f"  Memory / device  {target.memory_gb_per_device:.1f} GB",
        f"  Architecture     {target.architecture}",
        f"  Tier / location  {target.tier} — {target.location}",
        f"  Status           {target.status}",
    ]
    if target.observed_gpu_utilization_pct is not None:
        lines.append(
            f"  Utilization      {target.observed_gpu_utilization_pct:.0f}% GPU, "
            f"{target.observed_memory_utilization_pct:.0f}% memory (observed)"
        )
    if target.discovered_at is not None:
        lines.append(f"  Discovered at    {target.discovered_at.isoformat()}")
    lines.append("")
    lines.append(f"  {target.notes}")
    lines.append("")
    lines.append("Run `forgeway discover --json` for the full ComputeTarget record.")
    return "\n".join(lines)


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        target = run_discovery()
    except DiscoveryError as e:
        print(f"forgeway discover: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(target.model_dump_json(indent=2))
    else:
        print(format_human(target))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgeway", description="Forgeway workload intelligence CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser(
        "discover", help="Detect local compute hardware and describe it as a ComputeTarget."
    )
    discover_parser.add_argument(
        "--json", action="store_true", help="Emit a Forgeway ComputeTarget JSON object instead of text."
    )
    discover_parser.set_defaults(func=cmd_discover)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # last-resort safety net — never show a raw traceback
        print(f"forgeway: unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
