"""Request and response models, explicit and separate from the domain.

This separation is what makes FR-022 true. With an explicit model, a new field in
the domain does **not** appear in the API on its own: somebody has to add it, and
that is exactly the behaviour wanted for a network surface with two secrets in
play. Serialising the domain directly would turn every future field into a leak by
default.

The cost is a hand-written mapping that could drift. A guard test compares the
domain fields with the exposed ones and fails when a new one appears without a
decision.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

class ControllerHealth(BaseModel):
    liveness: str = Field(
        description="live, live_degraded, stale or never_seen",
        examples=["live"],
    )
    state_is_current: bool = Field(
        description=(
            "False when the controller has not been seen recently. The output "
            "state below is then the LAST KNOWN state, not the current one."
        )
    )
    last_seen_at: datetime | None = None
    age_seconds: float | None = None
    started_at: datetime | None = None
    degraded: bool = False
    driver_kind: str | None = None
    tolerance_seconds: float | None = None
    multiple_controllers_suspected: bool = Field(
        default=False,
        description=(
            "True when more than one controller appears to be running against "
            "this database. Two processes switching the same relays is an "
            "electrical hazard; the API flags it and does not arbitrate."
        ),
    )


class PowerSnapshot(BaseModel):
    instant_w: int
    limit_w: int
    percent_of_limit: float


class HeaterState(BaseModel):
    id: str
    name: str
    enabled: bool
    power_w: int
    output_on: bool | None = Field(
        default=None,
        description=(
            "Whether the output is on RIGHT NOW. **Null when the state is not "
            "current**, so a client that reads only this field can never render a "
            "heater as charging without proof. The last known value is in "
            "`last_known_output_on`."
        ),
    )
    last_known_output_on: bool = Field(
        description="The last recorded value, whether or not it is still current."
    )
    changed_at: datetime | None = Field(
        default=None, description="When that last recorded change happened."
    )


class PlanSlotView(BaseModel):
    start: datetime
    end: datetime
    heater_ids: list[str]


class PlanSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    slot_minutes: int
    installation_revision: int
    created_at: datetime
    slots: list[PlanSlotView]


class ForecastSummary(BaseModel):
    date: date
    source: str = Field(description="aemet, simulated or fallback")
    average_temperature_c: float
    minimum_temperature_c: float | None = None
    maximum_temperature_c: float | None = None
    municipality: str | None = None


class AllocationSummary(BaseModel):
    heater_id: str
    requested_minutes: int
    allocated_minutes: int
    unmet_minutes: int


class StatusResponse(BaseModel):
    observed_at: datetime
    controller: ControllerHealth
    power: PowerSnapshot | None = Field(
        default=None,
        description=(
            "Null when the state is not current: an instantaneous power nobody "
            "can confirm is worse than none."
        ),
    )
    heaters: list[HeaterState]
    plan: PlanSummary | None = Field(
        default=None,
        description="Null when no window contains the moment of the query.",
    )
    forecast: ForecastSummary | None = None
    allocations: list[AllocationSummary] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

class ThermalProfileView(BaseModel):
    target_temperature_c: float
    design_outdoor_temperature_c: float
    thermal_factor: float
    min_charge: float
    max_charge: float


class OutputView(BaseModel):
    kind: str
    pin: int | None = None
    active_high: bool


class HeaterResponse(BaseModel):
    id: str
    name: str
    model: str | None = None
    power_kw: float
    full_charge_hours: float
    target_charge: float
    priority: int
    enabled: bool
    output: OutputView
    thermal: ThermalProfileView | None = None


class ScheduleView(BaseModel):
    timezone: str
    start_time: str
    end_time: str
    weekdays: list[int]


class WeatherView(BaseModel):
    provider: str
    municipality_code: str | None = None
    #: The NAME of the environment variable, never its value.
    api_key_env: str | None = None
    timeout_seconds: float | None = None
    simulated_average_temperature_c: float | None = None
    simulated_minimum_temperature_c: float | None = None
    fallback_average_temperature_c: float | None = None
    fallback_minimum_temperature_c: float | None = None
    retry_minutes: int
    refresh_minutes: int


class ConfigResponse(BaseModel):
    config_revision: int
    schema_revision: str
    max_total_power_kw: float
    slot_minutes: int
    window_minutes: int
    log_level: str
    state_file: str
    poll_seconds: float
    retention_days: int | None
    schedule: ScheduleView | None = None
    weather: WeatherView | None = None
    heaters: list[HeaterResponse]


class SetFieldRequest(BaseModel):
    revision: int = Field(
        description=(
            "The configuration revision the change is based on. Mandatory: it is "
            "the optimistic lock that stops two clients losing each other's edits."
        )
    )
    field: str
    value: str


class AddHeaterRequest(BaseModel):
    revision: int
    id: str
    power_kw: float
    full_charge_hours: float
    name: str | None = None
    model: str | None = None
    target_charge: float = 1.0
    priority: int = 0
    enabled: bool = True
    output: str = "simulated"
    pin: int | None = None
    active_high: bool = True
    target_temperature_c: float | None = None
    design_outdoor_temperature_c: float | None = None
    thermal_factor: float = 1.0
    min_charge: float = 0.0
    max_charge: float = 1.0


class ChangeResponse(BaseModel):
    entity: str
    entity_key: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    action: str
    revision_before: int
    revision_after: int


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

class PlanHistoryItem(BaseModel):
    id: int
    created_at: datetime
    window_start: datetime
    window_end: datetime
    slot_minutes: int
    installation_revision: int
    forecast_id: int | None = None


class ForecastHistoryItem(BaseModel):
    id: int
    forecast_date: date
    source: str
    average_temperature_c: float
    minimum_temperature_c: float | None = None
    maximum_temperature_c: float | None = None
    municipality: str | None = None
    retrieved_at: datetime


class TransitionHistoryItem(BaseModel):
    id: int
    heater_id: str
    state: bool
    occurred_at: datetime
    plan_id: int | None = None


class PlanPage(BaseModel):
    items: list[PlanHistoryItem]
    limit_applied: int
    has_more: bool
    next_cursor: str | None = None


class ForecastPage(BaseModel):
    items: list[ForecastHistoryItem]
    limit_applied: int
    has_more: bool
    next_cursor: str | None = None


class TransitionPage(BaseModel):
    items: list[TransitionHistoryItem]
    limit_applied: int
    has_more: bool
    next_cursor: str | None = None


class PruneResponse(BaseModel):
    deleted: dict[str, int]
    total: int
    retention_days: int | None
    unlimited: bool


class ErrorResponse(BaseModel):
    code: str
    message: str
    field: str | None = None
    heater_id: str | None = None


ERROR_RESPONSES: dict[int | str, dict] = {
    401: {"model": ErrorResponse, "description": "Missing or wrong credential"},
    404: {"model": ErrorResponse, "description": "Unknown field, heater or resource"},
    409: {"model": ErrorResponse, "description": "Stale revision, or id in use"},
    422: {"model": ErrorResponse, "description": "Invalid result, or rejected secret"},
    503: {
        "model": ErrorResponse,
        "description": "Database unavailable, schema unusable, or no configuration",
    },
}

READ_RESPONSES: dict[int | str, dict] = {
    401: ERROR_RESPONSES[401],
    503: ERROR_RESPONSES[503],
}


__all__ = [
    "ERROR_RESPONSES",
    "READ_RESPONSES",
    "AddHeaterRequest",
    "AllocationSummary",
    "ChangeResponse",
    "ConfigResponse",
    "ControllerHealth",
    "ErrorResponse",
    "ForecastPage",
    "ForecastSummary",
    "HeaterResponse",
    "HeaterState",
    "PlanPage",
    "PlanSummary",
    "PowerSnapshot",
    "PruneResponse",
    "SetFieldRequest",
    "StatusResponse",
    "TransitionPage",
]
