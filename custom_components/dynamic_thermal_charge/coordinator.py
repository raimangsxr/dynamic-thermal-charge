"""Shared thirty-second operational snapshot and dynamic inventory handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DynamicThermalChargeAuthError,
    DynamicThermalChargeClient,
    DynamicThermalChargeConflictError,
    DynamicThermalChargeConnectionError,
    DynamicThermalChargeValidationError,
    validate_snapshot,
)
from .const import DOMAIN, MANUFACTURER, POLL_INTERVAL, VERSION

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
        self.controller_device_id: str | None = None
        self._platforms: dict[
            str,
            tuple[EntityFactory, UniqueIdFactory, Callable[[list[Any]], None]],
        ] = {}
        self._known_accumulator_ids: set[str] = set()
        self._pending_snapshot: dict[str, Any] | None = None
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
            snapshot = validate_snapshot(
                snapshot,
                expected_installation_id=self.entry.unique_id,
            )
        except DynamicThermalChargeAuthError as exc:
            raise ConfigEntryAuthFailed("backend token rejected") from exc
        except DynamicThermalChargeConnectionError as exc:
            raise UpdateFailed("backend snapshot unavailable") from exc

        # DataUpdateCoordinator assigns ``self.data`` only after this method
        # returns.  Keep the authoritative snapshot available while entities
        # are reconciled so their stable IDs and device names use this result.
        self._pending_snapshot = snapshot
        try:
            await self._async_reconcile(snapshot)
        finally:
            self._pending_snapshot = None
        return snapshot

    async def _async_reconcile(self, snapshot: dict[str, Any]) -> None:
        current_ids = {
            str(item["id"])
            for item in snapshot.get("accumulators", ())
            if isinstance(item, dict) and item.get("id") is not None
        }
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
            if removed_ids:
                self._remove_accumulator_entities(removed_ids, unique_ids)
            setattr(self, f"_known_{platform}", current_ids)

        removed_from_inventory = self._known_accumulator_ids - current_ids
        self._known_accumulator_ids = current_ids
        if removed_from_inventory:
            self._remove_accumulator_devices(removed_from_inventory)

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
        """Send an optimistic command, refreshing once on a revision conflict."""
        for attempt in range(2):
            if self.data is None or not self.last_update_success:
                await self.async_request_refresh()
            if self.data is None or not self.last_update_success:
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

    def _remove_accumulator_entities(
        self,
        accumulator_ids: set[str] | list[str],
        unique_ids: UniqueIdFactory,
    ) -> None:
        registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(registry, self.entry.entry_id)
        entries_by_unique_id = {item.unique_id: item for item in entries}
        for accumulator_id in accumulator_ids:
            for entity_unique_id in unique_ids(accumulator_id):
                if (entity := entries_by_unique_id.get(entity_unique_id)) is not None:
                    registry.async_remove(entity.entity_id)

    def _remove_accumulator_devices(self, accumulator_ids: set[str]) -> None:
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.entry.entry_id
        )
        for accumulator_id in accumulator_ids:
            identifier = (DOMAIN, f"{installation_id(self)}:{accumulator_id}")
            devices_by_id = {
                device.id: device
                for device in device_registry.async_get_devices(
                    identifiers={identifier},
                    config_entry_id=self.entry.entry_id,
                )
            }
            if child := device_registry.async_get_child_device_by_identifier(
                identifier, self.entry.entry_id
            ):
                devices_by_id[child.id] = child
            for device in devices_by_id.values():
                # If an entity from another platform was not known by the
                # platform-specific unique-id factory, remove it as well.  The
                # controller has a different identifier and is never touched.
                if any(item.device_id == device.id for item in entries):
                    for item in entries:
                        if item.device_id == device.id:
                            entity_registry.async_remove(item.entity_id)
                if not any(
                    item.device_id == device.id
                    for item in er.async_entries_for_config_entry(
                        entity_registry, self.entry.entry_id
                    )
                ):
                    device_registry.async_remove_device(device.id)


def accumulator_from_snapshot(
    coordinator: DynamicThermalChargeCoordinator,
    accumulator_id: str,
) -> dict[str, Any] | None:
    snapshot = coordinator.data or coordinator._pending_snapshot
    if not coordinator.last_update_success or snapshot is None:
        return None
    return next(
        (
            item
            for item in snapshot.get("accumulators", ())
            if isinstance(item, dict) and str(item.get("id")) == str(accumulator_id)
        ),
        None,
    )


def installation_id(coordinator: DynamicThermalChargeCoordinator) -> str:
    snapshot = coordinator.data or coordinator._pending_snapshot
    if snapshot is not None:
        installation = snapshot.get("installation")
        if isinstance(installation, dict) and installation.get("id") is not None:
            return str(installation["id"])
    return coordinator.entry.unique_id or coordinator.entry.entry_id


def controller_device_id(coordinator: DynamicThermalChargeCoordinator) -> str:
    """Return the registered parent device ID, creating it when needed."""
    if coordinator.controller_device_id is not None:
        return coordinator.controller_device_id
    device_registry = dr.async_get(coordinator.hass)
    identifier = (DOMAIN, installation_id(coordinator))
    device = device_registry.async_get_device_by_identifier(
        identifier,
        coordinator.entry.entry_id,
    )
    if device is None:
        snapshot = coordinator.data or coordinator._pending_snapshot or {}
        installation = snapshot.get("installation", {})
        device = device_registry.async_get_or_create(
            config_entry_id=coordinator.entry.entry_id,
            identifiers={identifier},
            name=str(installation.get("name") or "Dynamic Thermal Charge"),
            manufacturer=MANUFACTURER,
            model="Controller",
            sw_version=VERSION,
        )
    coordinator.controller_device_id = device.id
    return device.id


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
    "controller_device_id",
    "controller_unique_id",
    "installation_id",
]
