"""Shared thirty-second operational snapshot and dynamic inventory handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DynamicThermalChargeAuthError,
    DynamicThermalChargeClient,
    DynamicThermalChargeConflictError,
    DynamicThermalChargeConnectionError,
    DynamicThermalChargeValidationError,
)
from .const import DOMAIN, POLL_INTERVAL

logger = logging.getLogger(__name__)


EntityFactory = Callable[[str], list[Any]]
UniqueIdFactory = Callable[[str], tuple[str, ...]]


class DynamicThermalChargeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep one coherent backend snapshot for every Home Assistant entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DynamicThermalChargeClient,
        entry: ConfigEntry,
    ) -> None:
        self.client = client
        self.entry = entry
        self._platforms: dict[str, tuple[EntityFactory, UniqueIdFactory, Callable[[list[Any]], None]]] = {}
        super().__init__(
            hass,
            logger=logger,
            config_entry=entry,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
            update_method=self._async_update_data,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot = await self.client.async_snapshot()
        except DynamicThermalChargeAuthError as exc:
            raise ConfigEntryAuthFailed("backend token rejected") from exc
        except DynamicThermalChargeConnectionError as exc:
            raise UpdateFailed("backend snapshot unavailable") from exc
        await self._async_reconcile(snapshot)
        return snapshot

    async def _async_reconcile(self, snapshot: dict[str, Any]) -> None:
        current_ids = {
            str(item["id"])
            for item in snapshot.get("accumulators", ())
            if isinstance(item, dict) and item.get("id")
        }
        registry = er.async_get(self.hass)
        for platform, (factory, unique_ids, add_entities) in self._platforms.items():
            known_ids = getattr(self, f"_known_{platform}", set())
            new_ids = sorted(current_ids - known_ids)
            if new_ids:
                add_entities(
                    [
                        entity
                        for accumulator_id in new_ids
                        for entity in factory(accumulator_id)
                    ]
                )
            removed_ids = sorted(known_ids - current_ids)
            for accumulator_id in removed_ids:
                for unique_id in unique_ids(accumulator_id):
                    entity = next(
                        (
                            item
                            for item in er.async_entries_for_config_entry(
                                registry, self.entry.entry_id
                            )
                            if item.unique_id == unique_id
                        ),
                        None,
                    )
                    if entity is not None:
                        registry.async_remove(entity.entity_id)
            setattr(self, f"_known_{platform}", current_ids)

    async def async_register_dynamic_platform(
        self,
        platform: str,
        factory: EntityFactory,
        unique_ids: UniqueIdFactory,
        add_entities: Callable[[list[Any]], None],
    ) -> None:
        self._platforms[platform] = (factory, unique_ids, add_entities)
        setattr(self, f"_known_{platform}", set())
        if self.data is not None:
            await self._async_reconcile(self.data)

    async def async_command(
        self,
        command: Callable[[int], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Send an optimistic command, refresh once on a revision conflict."""
        for attempt in range(2):
            if self.data is None or not self.last_update_success:
                await self.async_request_refresh()
            if self.data is None:
                raise HomeAssistantError("backend snapshot is unavailable")
            revision = int(self.data["revision"])
            try:
                result = await command(revision)
            except DynamicThermalChargeConflictError as exc:
                if attempt == 0:
                    await self.async_request_refresh()
                    continue
                raise HomeAssistantError(str(exc)) from exc
            except DynamicThermalChargeAuthError as exc:
                raise ConfigEntryAuthFailed("backend token rejected") from exc
            except DynamicThermalChargeValidationError as exc:
                raise HomeAssistantError(str(exc)) from exc
            except DynamicThermalChargeConnectionError as exc:
                raise HomeAssistantError("backend command failed") from exc
            await self.async_request_refresh()
            return result
        raise HomeAssistantError("backend command conflicted twice")


def accumulator_from_snapshot(
    coordinator: DynamicThermalChargeCoordinator,
    accumulator_id: str,
) -> dict[str, Any] | None:
    if not coordinator.last_update_success or coordinator.data is None:
        return None
    return next(
        (
            item
            for item in coordinator.data.get("accumulators", ())
            if item.get("id") == accumulator_id
        ),
        None,
    )


def installation_id(coordinator: DynamicThermalChargeCoordinator) -> str:
    if coordinator.data is None:
        return coordinator.entry.unique_id or coordinator.entry.entry_id
    return str(coordinator.data["installation"]["id"])


def controller_unique_id(coordinator: DynamicThermalChargeCoordinator, key: str) -> str:
    return f"{DOMAIN}_{installation_id(coordinator)}_controller_{key}"


def accumulator_unique_id(
    coordinator: DynamicThermalChargeCoordinator,
    accumulator_id: str,
    key: str,
) -> str:
    return f"{DOMAIN}_{installation_id(coordinator)}_accumulator_{accumulator_id}_{key}"


__all__ = [
    "DynamicThermalChargeCoordinator",
    "accumulator_from_snapshot",
    "accumulator_unique_id",
    "controller_unique_id",
    "installation_id",
]
