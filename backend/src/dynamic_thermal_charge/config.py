"""Configuration validation, independent of where the configuration came from."""

from __future__ import annotations

from .models import AppConfig, Heater
from .persistence import ConfigValidationError


# --------------------------------------------------------------------------- #
# Origin-independent validation
#
# Constitution principle III requires configuration to be validated in full when
# loaded, whatever its origin, and rejected completely when any field is invalid.
# These are the cross-cutting invariants that a single edit can break and that no
# individual dataclass can see on its own; the per-entity invariants live in the
# ``__post_init__`` methods of ``models.py`` and remain the last line of defence.
# --------------------------------------------------------------------------- #


def validate_heaters(heaters: tuple[Heater, ...]) -> None:
    """Check the invariants that span heaters, naming both parties to a clash."""
    seen_ids: dict[str, int] = {}
    for index, heater in enumerate(heaters):
        if heater.id in seen_ids:
            raise ConfigValidationError(
                f"duplicate heater id {heater.id!r}: heater ids must be unique within "
                "an installation",
                field="heater_id",
                heater_id=heater.id,
            )
        seen_ids[heater.id] = index

    pins: dict[int, str] = {}
    for heater in heaters:
        if heater.output.kind != "gpio" or heater.output.pin is None:
            continue
        owner = pins.get(heater.output.pin)
        if owner is not None:
            raise ConfigValidationError(
                f"pin {heater.output.pin} is already assigned to heater {owner!r}",
                field="pin",
                heater_id=heater.id,
            )
        pins[heater.output.pin] = heater.id


def validate_config(config: AppConfig) -> None:
    """Check the invariants that span the whole installation."""
    if config.site.indoor_max_age_minutes <= 0:
        raise ConfigValidationError(
            "indoor_max_age_minutes must be positive",
            field="indoor_max_age_minutes",
        )
    if (
        config.site.indoor_min_plausible_c
        >= config.site.indoor_max_plausible_c
    ):
        raise ConfigValidationError(
            "indoor_min_plausible_c must be lower than indoor_max_plausible_c",
            field="indoor_min_plausible_c",
        )
    validate_heaters(config.heaters)

    if config.schedule is not None:
        for field, configured_time in (
            ("start_time", config.schedule.start_time),
            ("end_time", config.schedule.end_time),
        ):
            minutes = configured_time.hour * 60 + configured_time.minute
            if minutes % config.site.slot_minutes:
                raise ConfigValidationError(
                    f"{field} {configured_time:%H:%M} does not align with "
                    f"slot_minutes {config.site.slot_minutes}",
                    field=field,
                )
        if config.schedule.window_minutes % config.site.slot_minutes:
            raise ConfigValidationError(
                "the charge window defined by start_time and end_time must contain a "
                f"whole number of {config.site.slot_minutes}-minute slots",
                field="window_minutes",
            )

    if any(heater.thermal is not None for heater in config.heaters) and config.weather is None:
        raise ConfigValidationError(
            "a thermal profile requires a weather provider; configure weather or "
            "remove the thermal profiles",
            field="weather",
        )
