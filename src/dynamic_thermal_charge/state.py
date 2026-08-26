"""Atomic persistence for the currently active charge plan."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from .scheduler import ScheduleResult, ScheduleSlot


logger = logging.getLogger(__name__)


class PlanStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, plan: ScheduleResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "slots": [
                {
                    "start": slot.start.isoformat(),
                    "end": slot.end.isoformat(),
                    "heater_ids": list(slot.heater_ids),
                    "total_power_w": slot.total_power_w,
                }
                for slot in plan.slots
            ],
            "allocated_minutes": plan.allocated_minutes,
            "unmet_minutes": plan.unmet_minutes,
        }
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            logger.info("Persisted active charge plan to %s", self.path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def load(self) -> ScheduleResult | None:
        if not self.path.exists():
            return None
        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("plan state must be a JSON object")
            if payload.get("version") != 1:
                raise ValueError("unsupported plan state version")
            slots = tuple(
                ScheduleSlot(
                    start=datetime.fromisoformat(item["start"]),
                    end=datetime.fromisoformat(item["end"]),
                    heater_ids=tuple(item["heater_ids"]),
                    total_power_w=int(item["total_power_w"]),
                )
                for item in payload["slots"]
            )
            plan = ScheduleResult(
                slots=slots,
                allocated_minutes={
                    str(key): int(value)
                    for key, value in payload["allocated_minutes"].items()
                },
                unmet_minutes={
                    str(key): int(value)
                    for key, value in payload["unmet_minutes"].items()
                },
            )
        except (
            AttributeError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            logger.error("Ignoring invalid persisted charge plan %s: %s", self.path, exc)
            return None
        logger.info("Loaded persisted charge plan from %s", self.path)
        return plan
