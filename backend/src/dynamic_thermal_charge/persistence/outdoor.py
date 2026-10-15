"""Latest outdoor reading used by calibration (not a general telemetry history)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from ..thermal_calibration import validate_outdoor_temperature
from .engine import transaction
from .mapping import from_utc, to_utc
from .schema import outdoor_temperature
from .url import StoreLocation


@dataclass(frozen=True)
class OutdoorTemperature:
    temperature_c: float
    received_at: datetime


class SqlOutdoorTemperatureRepository:
    def __init__(self, engine: Engine, installation_id: int, location: StoreLocation | None = None) -> None:
        self._engine = engine
        self._installation_id = installation_id
        self._location = location

    def record(self, temperature_c: float, received_at: datetime) -> None:
        validate_outdoor_temperature(temperature_c)
        moment = to_utc(received_at)
        with transaction(self._engine, self._location) as connection:
            existing = connection.execute(
                select(outdoor_temperature.c.installation_id).where(
                    outdoor_temperature.c.installation_id == self._installation_id
                )
            ).first()
            values = {
                "temperature_c": float(temperature_c),
                "received_at": moment,
                "updated_at": moment,
            }
            if existing is None:
                connection.execute(
                    insert(outdoor_temperature).values(
                        installation_id=self._installation_id, **values
                    )
                )
            else:
                connection.execute(
                    update(outdoor_temperature)
                    .where(outdoor_temperature.c.installation_id == self._installation_id)
                    .values(**values)
                )

    def latest(self) -> OutdoorTemperature | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(outdoor_temperature).where(
                    outdoor_temperature.c.installation_id == self._installation_id
                )
            ).mappings().first()
        if row is None:
            return None
        return OutdoorTemperature(float(row["temperature_c"]), from_utc(row["received_at"]))


__all__ = ["OutdoorTemperature", "SqlOutdoorTemperatureRepository"]
