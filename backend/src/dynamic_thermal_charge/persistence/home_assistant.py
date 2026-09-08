"""Durable control state shared by the API and the autonomous controller.

The name describes the first consumer, not the contract.  This module stores
generic installation commands and telemetry that can be consumed by any local
client.  It never imports Home Assistant or FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from . import ConfigConflictError, ConfigStoreEmptyError, ConfigValidationError
from .engine import store_errors, transaction
from .mapping import parse_temperature_target_end_time, parse_time, to_utc
from .schema import (
    automatic_plan,
    charge_planning_site,
    heater_charge_config,
    installation,
    temperature_target,
)
from .url import StoreLocation


CONTROL_MODES = frozenset({"AUTO", "OFF"})


@dataclass(frozen=True)
class ControlState:
    installation_uuid: str
    revision: int
    automatic_control_enabled: bool
    recalculation_requested_generation: int
    recalculation_processed_generation: int
    heater_modes: dict[str, str]
    damper_topics: dict[str, str | None]

    @property
    def recalculation_pending(self) -> bool:
        return self.recalculation_requested_generation > self.recalculation_processed_generation

    def heater_enabled(self, heater_id: str) -> bool:
        return self.automatic_control_enabled and self.heater_modes.get(heater_id, "AUTO") == "AUTO"


@dataclass(frozen=True)
class ControlCommandResult:
    state: ControlState
    changed: bool


class SqlHomeAssistantRepository:
    """Read and atomically update the durable operational control contract."""

    def __init__(
        self,
        configuration_engine: Engine,
        application_engine: Engine,
        installation_id: int,
        configuration_location: StoreLocation | None = None,
        application_location: StoreLocation | None = None,
    ) -> None:
        self._configuration = configuration_engine
        self._application = application_engine
        self._installation_id = installation_id
        self._configuration_location = configuration_location
        self._application_location = application_location

    def control_state(self) -> ControlState:
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                row = connection.execute(
                    select(installation).where(installation.c.id == self._installation_id)
                ).mappings().first()
                if row is None:
                    raise ConfigStoreEmptyError("the configuration database holds no installation")
                modes = connection.execute(
                    select(
                        heater_charge_config.c.heater_id,
                        heater_charge_config.c.control_mode,
                        heater_charge_config.c.damper_topic,
                    ).where(
                        heater_charge_config.c.installation_id == self._installation_id
                    )
                ).mappings().all()
        return ControlState(
            installation_uuid=_installation_uuid(row),
            revision=int(row["revision"]),
            automatic_control_enabled=bool(row.get("automatic_control_enabled", True)),
            recalculation_requested_generation=int(
                row.get("recalculation_requested_generation", 0)
            ),
            recalculation_processed_generation=int(
                row.get("recalculation_processed_generation", 0)
            ),
            heater_modes={
                str(item["heater_id"]): _normalize_mode(item.get("control_mode"))
                for item in modes
            },
            damper_topics={
                str(item["heater_id"]): (
                    None
                    if item.get("damper_topic") is None
                    else str(item["damper_topic"])
                )
                for item in modes
            },
        )

    def installation_uuid(self) -> str:
        return self.control_state().installation_uuid

    def set_automatic_control(
        self,
        enabled: bool,
        *,
        expected_revision: int,
    ) -> ControlCommandResult:
        with transaction(self._configuration, self._configuration_location) as connection:
            row = self._locked_installation(connection)
            current_revision = int(row["revision"])
            _require_revision(current_revision, expected_revision)
            current = bool(row.get("automatic_control_enabled", True))
            if current == enabled:
                changed = False
            else:
                requested = int(row.get("recalculation_requested_generation", 0)) + 1
                changed = connection.execute(
                    update(installation)
                    .where(
                        (installation.c.id == self._installation_id)
                        & (installation.c.revision == expected_revision)
                    )
                    .values(
                        automatic_control_enabled=bool(enabled),
                        revision=expected_revision + 1,
                        recalculation_requested_generation=requested,
                        updated_at=to_utc(datetime.now(timezone.utc)),
                    )
                ).rowcount
                if changed != 1:
                    raise ConfigConflictError("installation control changed; refresh before retrying")
        if not enabled:
            self._deactivate_active_plan()
        return ControlCommandResult(self.control_state(), bool(changed))

    def request_recalculation(self, *, expected_revision: int) -> ControlCommandResult:
        with transaction(self._configuration, self._configuration_location) as connection:
            row = self._locked_installation(connection)
            _require_revision(int(row["revision"]), expected_revision)
            requested = int(row.get("recalculation_requested_generation", 0)) + 1
            changed = connection.execute(
                update(installation)
                .where(
                    (installation.c.id == self._installation_id)
                    & (installation.c.revision == expected_revision)
                )
                .values(
                    revision=expected_revision + 1,
                    recalculation_requested_generation=requested,
                    updated_at=to_utc(datetime.now(timezone.utc)),
                )
            ).rowcount
            if changed != 1:
                raise ConfigConflictError("installation control changed; refresh before retrying")
        return ControlCommandResult(self.control_state(), True)

    def set_heater_mode(
        self,
        heater_id: str,
        mode: str,
        *,
        expected_revision: int,
    ) -> ControlCommandResult:
        normalized = str(mode).strip().upper()
        if normalized not in CONTROL_MODES:
            raise ConfigValidationError(
                "mode must be AUTO or OFF", field="mode", heater_id=heater_id
            )
        with transaction(self._configuration, self._configuration_location) as connection:
            row = self._locked_installation(connection)
            _require_revision(int(row["revision"]), expected_revision)
            existing = connection.execute(
                select(heater_charge_config).where(
                    (heater_charge_config.c.installation_id == self._installation_id)
                    & (heater_charge_config.c.heater_id == heater_id)
                )
            ).mappings().first()
            if existing is None:
                raise ConfigValidationError(
                    f"heater {heater_id!r} does not exist", field="heater_id", heater_id=heater_id
                )
            if _normalize_mode(existing.get("control_mode")) == normalized:
                changed = 0
            else:
                requested = int(row.get("recalculation_requested_generation", 0)) + 1
                changed = connection.execute(
                    update(heater_charge_config)
                    .where(
                        (heater_charge_config.c.installation_id == self._installation_id)
                        & (heater_charge_config.c.heater_id == heater_id)
                    )
                    .values(control_mode=normalized)
                ).rowcount
                if changed != 1:
                    raise ConfigConflictError("heater control changed; refresh before retrying")
                changed = connection.execute(
                    update(installation)
                    .where(
                        (installation.c.id == self._installation_id)
                        & (installation.c.revision == expected_revision)
                    )
                    .values(
                        revision=expected_revision + 1,
                        recalculation_requested_generation=requested,
                        updated_at=to_utc(datetime.now(timezone.utc)),
                    )
                ).rowcount
                if changed != 1:
                    raise ConfigConflictError("installation control changed; refresh before retrying")
        if normalized == "OFF":
            self._deactivate_active_plan()
        return ControlCommandResult(self.control_state(), bool(changed))

    def set_damper_topic(
        self,
        heater_id: str,
        topic: str | None,
        *,
        expected_revision: int,
    ) -> ControlCommandResult:
        normalized = None if topic is None or not str(topic).strip() else str(topic).strip()
        changed = 0
        with transaction(self._configuration, self._configuration_location) as connection:
            row = self._locked_installation(connection)
            _require_revision(int(row["revision"]), expected_revision)
            existing = connection.execute(
                select(
                    heater_charge_config.c.heater_id,
                    heater_charge_config.c.damper_topic,
                ).where(
                    (heater_charge_config.c.installation_id == self._installation_id)
                    & (heater_charge_config.c.heater_id == heater_id)
                )
            ).mappings().first()
            if existing is None:
                raise ConfigValidationError("unknown heater", field="heater_id", heater_id=heater_id)
            if existing["damper_topic"] == normalized:
                changed = 0
            else:
                changed = connection.execute(
                    update(heater_charge_config)
                    .where(
                        (heater_charge_config.c.installation_id == self._installation_id)
                        & (heater_charge_config.c.heater_id == heater_id)
                    )
                    .values(damper_topic=normalized)
                ).rowcount
                if changed != 1:
                    raise ConfigConflictError("damper configuration changed; refresh before retrying")
                revision_changed = connection.execute(
                    update(installation)
                    .where(
                        (installation.c.id == self._installation_id)
                        & (installation.c.revision == expected_revision)
                    )
                    .values(
                        revision=expected_revision + 1,
                        updated_at=to_utc(datetime.now(timezone.utc)),
                    )
                ).rowcount
                if revision_changed != 1:
                    raise ConfigConflictError("installation control changed; refresh before retrying")
        return ControlCommandResult(self.control_state(), bool(changed))

    def set_active_temperature_target(
        self,
        heater_id: str,
        target_temperature_c: float,
        *,
        at: datetime,
        expected_revision: int,
    ) -> ControlCommandResult:
        if not math.isfinite(target_temperature_c) or not -50 <= target_temperature_c <= 80:
            raise ConfigValidationError(
                "target_temperature_c must be finite and between -50 and 80",
                field="target_temperature_c",
                heater_id=heater_id,
            )
        with transaction(self._configuration, self._configuration_location) as connection:
            installation_row = self._locked_installation(connection)
            _require_revision(int(installation_row["revision"]), expected_revision)
            timezone_name = installation_row.get("timezone")
            if not timezone_name:
                raise ConfigValidationError(
                    "there is no active weekly target without an installation timezone",
                    field="target_temperature_c",
                    heater_id=heater_id,
                )
            try:
                zone = ZoneInfo(str(timezone_name))
            except Exception as exc:
                raise ConfigValidationError(
                    "the installation timezone is invalid", field="timezone"
                ) from exc
            rows = connection.execute(
                select(temperature_target).where(
                    (temperature_target.c.installation_id == self._installation_id)
                    & (temperature_target.c.heater_id == heater_id)
                    & temperature_target.c.enabled.is_(True)
                ).order_by(temperature_target.c.id)
            ).mappings().all()
            active = [row for row in rows if _target_is_active(row, at, zone)]
            if not active:
                raise ConfigValidationError(
                    "there is no active weekly temperature target for this accumulator",
                    field="target_temperature_c",
                    heater_id=heater_id,
                )
            if len(active) > 1:
                raise ConfigValidationError(
                    "multiple weekly temperature targets are active; resolve the overlap first",
                    field="target_temperature_c",
                    heater_id=heater_id,
                )
            target_id = active[0]["id"]
            connection.execute(
                update(temperature_target)
                .where(temperature_target.c.id == target_id)
                .values(
                    target_temperature_c=float(target_temperature_c),
                    updated_at=to_utc(datetime.now(timezone.utc)),
                )
            )
            site = connection.execute(
                select(charge_planning_site.c.revision).where(
                    charge_planning_site.c.installation_id == self._installation_id
                )
            ).scalar()
            if site is not None:
                connection.execute(
                    update(charge_planning_site)
                    .where(charge_planning_site.c.installation_id == self._installation_id)
                    .values(revision=int(site) + 1)
                )
            requested = int(installation_row.get("recalculation_requested_generation", 0)) + 1
            changed = connection.execute(
                update(installation)
                .where(
                    (installation.c.id == self._installation_id)
                    & (installation.c.revision == expected_revision)
                )
                .values(
                    revision=expected_revision + 1,
                    recalculation_requested_generation=requested,
                    updated_at=to_utc(datetime.now(timezone.utc)),
                )
            ).rowcount
            if changed != 1:
                raise ConfigConflictError("installation control changed; refresh before retrying")
        return ControlCommandResult(self.control_state(), True)

    def mark_recalculation_processed(self, generation: int) -> None:
        with transaction(self._configuration, self._configuration_location) as connection:
            connection.execute(
                update(installation)
                .where(
                    (installation.c.id == self._installation_id)
                    & (installation.c.recalculation_processed_generation < generation)
                )
                .values(recalculation_processed_generation=generation)
            )

    def _locked_installation(self, connection):
        row = connection.execute(
            select(installation).where(installation.c.id == self._installation_id)
        ).mappings().first()
        if row is None:
            raise ConfigStoreEmptyError("the configuration database holds no installation")
        return row

    def _deactivate_active_plan(self) -> None:
        with transaction(self._application, self._application_location) as connection:
            connection.execute(
                update(automatic_plan)
                .where(
                    (automatic_plan.c.installation_id == self._installation_id)
                    & automatic_plan.c.active.is_(True)
                )
                .values(active=False)
            )


def _installation_uuid(row: Any) -> str:
    value = row.get("installation_uuid")
    if value:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ConfigValidationError("installation UUID is invalid", field="installation_uuid") from exc
    # This path only exists for a store being read during an incomplete legacy
    # migration. Never invent an identity in a read operation.
    raise ConfigValidationError("installation UUID is missing", field="installation_uuid")


def _normalize_mode(value: Any) -> str:
    mode = "AUTO" if value is None else str(value).upper()
    return mode if mode in CONTROL_MODES else "OFF"


def _require_revision(current: int, expected: int) -> None:
    if current != expected:
        raise ConfigConflictError(
            "installation control changed; refresh the snapshot before retrying"
        )


def _target_is_active(row: Any, at: datetime, zone: ZoneInfo) -> bool:
    local = at.astimezone(zone) if at.tzinfo is not None else at.replace(tzinfo=zone)
    start = parse_time(str(row["start_time"]), "start_time")
    end = parse_temperature_target_end_time(str(row["end_time"]), "end_time")
    start_minutes = start.hour * 60 + start.minute
    end_minutes = 24 * 60 if str(row["end_time"]) == "24:00" else end.hour * 60 + end.minute
    weekdays = tuple(int(item) for item in str(row["weekdays"]).split(",") if item != "")
    if start == end and str(row["end_time"]) != "24:00":
        return local.weekday() in weekdays
    local_minutes = local.hour * 60 + local.minute
    if end_minutes > start_minutes:
        return local.weekday() in weekdays and start_minutes <= local_minutes < end_minutes
    if end_minutes == start_minutes:
        return local.weekday() in weekdays
    if local.weekday() in weekdays and local_minutes >= start_minutes:
        return True
    previous_weekday = (local.weekday() - 1) % 7
    return previous_weekday in weekdays and local_minutes < end_minutes


__all__ = [
    "CONTROL_MODES",
    "ControlCommandResult",
    "ControlState",
    "SqlHomeAssistantRepository",
]
