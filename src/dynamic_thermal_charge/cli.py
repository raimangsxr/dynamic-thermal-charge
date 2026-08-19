"""Command-line entry point for planning a simulated charge window."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .config import load_config
from .scheduler import ChargeScheduler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan storage-heater charging")
    parser.add_argument("config", type=Path, help="YAML installation configuration")
    parser.add_argument(
        "--start",
        type=datetime.fromisoformat,
        default=None,
        help="charge window start in ISO format (default: current time)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
        start = args.start or datetime.now().replace(second=0, microsecond=0)
        result = ChargeScheduler().build(config.site, config.heaters, start)
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    print("Charge plan")
    for slot in result.slots:
        active = ", ".join(slot.heater_ids) or "—"
        print(
            f"{slot.start:%Y-%m-%d %H:%M}–{slot.end:%H:%M}  "
            f"{slot.total_power_w / 1000:.1f} kW  {active}"
        )
    print("\nAllocated:")
    for heater in config.heaters:
        if heater.enabled:
            minutes = result.allocated_minutes[heater.id]
            print(f"- {heater.name}: {minutes / 60:g} h")
    if result.unmet_minutes:
        print("\nUnmet demand:")
        for heater_id, minutes in result.unmet_minutes.items():
            print(f"- {heater_id}: {minutes / 60:g} h")
        return 2
    return 0
