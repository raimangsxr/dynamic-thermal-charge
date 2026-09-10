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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


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
    timezone: str = "UTC"
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
    telemetry: list["ChargeTelemetryView"] = Field(default_factory=list)
    plan_status: str | None = None
    deficits: list["PlanningDeficitView"] = Field(default_factory=list)
    convergence_by_heater: dict[str, datetime | None] = Field(default_factory=dict)
    convergence_at: datetime | None = None
    guaranteed_until: datetime | None = None
    horizon_start: datetime | None = None
    horizon_end: datetime | None = None
    absence_reason: str | None = None
    forecast_status: str | None = None
    forecast_last_attempt_at: datetime | None = None
    forecast_last_error: str | None = None
    forecast_next_run_at: datetime | None = None
    forecast_next_run_kind: str | None = None
    forecast_stale: bool | None = None


class HourlyForecastPointView(BaseModel):
    timestamp: datetime
    temperature_c: float
    interpolated: bool = False


class PlanningForecastView(ForecastSummary):
    hourly_points: list[HourlyForecastPointView] = Field(default_factory=list)


class PlanningSlotView(PlanSlotView):
    total_power_w: int = 0
    temperature_c: float | None = None
    temperature_interpolated: bool = False
    stored_energy_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    stored_energy_next_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    indoor_temperature_c_by_heater: dict[str, float] = Field(default_factory=dict)
    indoor_temperature_next_c_by_heater: dict[str, float] = Field(default_factory=dict)
    target_temperature_c_by_heater: dict[str, float] = Field(default_factory=dict)
    heat_delivered_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    thermal_loss_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    temperature_shortfall_start_c_by_heater: dict[str, float] = Field(default_factory=dict)
    temperature_shortfall_c_by_heater: dict[str, float] = Field(default_factory=dict)
    charge_energy_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    heat_delivery_limit_kwh_by_heater: dict[str, float] = Field(default_factory=dict)


class PlanningTimelineSlotView(BaseModel):
    start: datetime
    end: datetime
    heater_ids: list[str]
    total_power_w: int = 0
    temperature_c: float | None = None
    temperature_interpolated: bool = False
    stored_energy_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    stored_energy_next_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    indoor_temperature_c_by_heater: dict[str, float] = Field(default_factory=dict)
    indoor_temperature_next_c_by_heater: dict[str, float] = Field(default_factory=dict)
    target_temperature_c_by_heater: dict[str, float] = Field(default_factory=dict)
    heat_delivered_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    thermal_loss_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    temperature_shortfall_start_c_by_heater: dict[str, float] = Field(default_factory=dict)
    temperature_shortfall_c_by_heater: dict[str, float] = Field(default_factory=dict)
    charge_energy_kwh_by_heater: dict[str, float] = Field(default_factory=dict)
    heat_delivery_limit_kwh_by_heater: dict[str, float] = Field(default_factory=dict)


class PlanningHeaterView(BaseModel):
    id: str
    name: str
    power_w: int
    capacity_kwh: float
    priority: int
    enabled: bool
    damper_topic: str | None = None
    setpoint_topic: str | None = None


class PlanningPlanView(BaseModel):
    window_start: datetime
    window_end: datetime
    slot_minutes: int
    installation_revision: int
    created_at: datetime
    slots: list[PlanningSlotView]


class PlanningResponse(BaseModel):
    observed_at: datetime
    timezone: str = "UTC"
    max_total_power_w: int
    plan: PlanningPlanView | None = None
    forecast: PlanningForecastView | None = None
    allocations: list[AllocationSummary] = Field(default_factory=list)
    heaters: list[PlanningHeaterView] = Field(default_factory=list)
    horizon_start: datetime | None = None
    horizon_end: datetime | None = None
    timeline: list[PlanningTimelineSlotView] = Field(default_factory=list)
    absence_reason: str | None = None
    telemetry: list["ChargeTelemetryView"] = Field(default_factory=list)
    plan_status: str | None = None
    deficits: list["PlanningDeficitView"] = Field(default_factory=list)
    convergence_by_heater: dict[str, datetime | None] = Field(default_factory=dict)
    convergence_at: datetime | None = None
    guaranteed_until: datetime | None = None
    preview_token: str | None = None
    temperature_targets_revision: int = 1
    forecast_status: str | None = None
    forecast_last_attempt_at: datetime | None = None
    forecast_last_error: str | None = None
    forecast_next_run_at: datetime | None = None
    forecast_next_run_kind: str | None = None
    forecast_stale: bool | None = None
    preview_job: "PlanningPreviewJobResponse | None" = None
    base_load_w: int = 0
    max_heating_power_w: int = 0
    temperature_targets: list["TemperatureTargetView"] = Field(default_factory=list)


class WeatherRefreshResponse(BaseModel):
    status: str
    forecast_status: str
    forecast_last_attempt_at: datetime
    forecast_last_error: str | None = None
    forecast_next_run_at: datetime | None = None
    forecast_next_run_kind: str | None = None
    forecast: PlanningForecastView | None = None


class ChargeTelemetryView(BaseModel):
    heater_id: str
    indoor_temperature_c: float | None = None
    stored_soc_percent: float | None = None
    indoor_received_at: datetime | None = None
    stored_soc_received_at: datetime | None = None
    state: str = "telemetry_stale"
    missing_fields: list[str] = Field(default_factory=list)
    oldest_age_seconds: float | None = None
    stored_energy_kwh: float | None = None


class PlanningDeficitView(BaseModel):
    heater_id: str | None = None
    requirement: str = ""
    achievable_value: float | None = None
    shortfall: float | None = None
    at: datetime | None = None
    reason: str
    target_temperature_c: float | None = None
    projected_temperature_c: float | None = None
    shortfall_c: float | None = None
    stored_energy_kwh: float | None = None
    stored_soc_percent: float | None = None
    target_window_start: datetime | None = None
    target_window_end: datetime | None = None
    affected_from: datetime | None = None
    affected_until: datetime | None = None
    observation_count: int = 1


class TemperatureTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heater_id: str = ""
    target_temperature_c: float = Field(ge=-50, le=80)
    start_time: str
    end_time: str
    weekdays: list[int] = Field(min_length=1)
    enabled: bool = True


class TemperatureTargetView(BaseModel):
    id: int | None = None
    heater_id: str
    target_temperature_c: float
    start_time: str
    end_time: str
    weekdays: list[int]
    enabled: bool = True


class PlanningPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature_targets: list[TemperatureTargetRequest] | None = None
    expected_revision: int | None = None


class PlanningPreviewResponse(BaseModel):
    token: str
    status: str
    score: list[float]
    window_start: datetime
    window_end: datetime
    horizon_start: datetime
    horizon_end: datetime
    slot_minutes: int
    slots: list[dict]
    deficits: list[PlanningDeficitView] = Field(default_factory=list)
    violations: list[PlanningDeficitView] = Field(default_factory=list)
    convergence_by_heater: dict[str, datetime | None] = Field(default_factory=dict)
    convergence_at: datetime | None = None
    guaranteed_until: datetime | None = None
    explanations: list[dict] = Field(default_factory=list)
    demand: list[dict] = Field(default_factory=list)
    temperature_targets: list[TemperatureTargetView] = Field(default_factory=list)
    operator_summary: dict = Field(default_factory=dict)


class PlanningCheckView(BaseModel):
    name: str
    status: str
    detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PlanningPreviewJobResponse(BaseModel):
    job_id: str
    status: str
    cancellation_requested: bool = False
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    checks: list[PlanningCheckView] = Field(default_factory=list)
    result: PlanningPreviewResponse | None = None
    operator_summary: dict = Field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None


class PlanningActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    temperature_targets: list[TemperatureTargetRequest] | None = None
    expected_revision: int


class AutomaticPlanAuditItem(BaseModel):
    id: int
    plan_id: int | None = None
    event: str
    reason: str
    details: dict
    occurred_at: datetime


class AutomaticPlanAuditPage(BaseModel):
    items: list[AutomaticPlanAuditItem]


class HeaterChargeConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    damper_topic: str | None = None
    setpoint_topic: str | None = None


class PlanningSiteConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    replan_minutes: int = Field(gt=0)
    planning_window_hours: StrictInt = Field(gt=0, le=48, default=12)
    forecast_horizon_hours: StrictInt = Field(gt=0, le=48)
    solver_time_limit_seconds: StrictInt = Field(gt=0, default=120)
    aemet_query_hour: int = Field(ge=0, le=23)
    contracted_power_w: int = Field(gt=0)
    max_heating_power_w: int = Field(gt=0)
    base_load_w: int = Field(ge=0, default=0)
    deviation_shortfall_tolerance_c: float = Field(gt=0, default=0.1)
    deviation_surplus_soc_percent: float = Field(gt=0, default=5.0)
    mqtt_simulation_enabled: bool = False
    mqtt_simulation_initial_temperature_c: float = Field(ge=-50, le=80, default=45.0)
    mqtt_simulation_publish_seconds: float = Field(gt=0, default=30.0)
    mqtt_simulation_topic_prefix: str = Field(min_length=1, default="dtc/sim")
    mqtt_simulation_thermal_loss_c_per_hour: float = Field(ge=0, default=2.0)

    @model_validator(mode="after")
    def validate_planning_durations(self):
        if self.planning_window_hours > self.forecast_horizon_hours:
            raise ValueError("planning_window_hours must not exceed forecast_horizon_hours")
        return self


class PlanningSiteConfigResponse(BaseModel):
    revision: int
    replan_minutes: int
    planning_window_hours: int
    forecast_horizon_hours: int
    solver_time_limit_seconds: int
    aemet_query_hour: int
    contracted_power_w: int
    max_heating_power_w: int
    base_load_w: int
    deviation_shortfall_tolerance_c: float = 0.1
    deviation_surplus_soc_percent: float = 5.0
    mqtt_simulation_enabled: bool
    mqtt_simulation_initial_temperature_c: float
    mqtt_simulation_publish_seconds: float
    mqtt_simulation_topic_prefix: str
    mqtt_simulation_thermal_loss_c_per_hour: float


class ControllerLogEvent(BaseModel):
    id: int
    occurred_at: datetime
    level: str
    logger: str
    message: str


class ControllerLogPage(BaseModel):
    items: list[ControllerLogEvent]
    limit_applied: int
    has_more: bool
    next_before_id: int | None = None


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

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
    full_discharge_hours: float = 10.0
    static_emission_percent: float = 20.0
    priority: int
    enabled: bool
    telemetry_topic: str | None = None
    output: OutputView
    room_thermal_capacity_kwh_per_c: float = 2.5
    room_heat_loss_kw_per_c: float = 0.12
    temperature_targets: list[TemperatureTargetView] = Field(default_factory=list)


class ScheduleView(BaseModel):
    timezone: str
    start_time: str
    end_time: str
    weekdays: list[int]


class ConfigResponse(BaseModel):
    config_revision: int
    schema_revision: str
    max_total_power_kw: float
    slot_minutes: int
    window_minutes: int
    indoor_max_age_minutes: int
    indoor_min_plausible_c: float
    indoor_max_plausible_c: float
    log_level: str
    poll_seconds: float
    retention_days: int | None
    schedule: ScheduleView | None = None
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


class PatchInstallationRequest(BaseModel):
    revision: int = Field(
        description=(
            "The configuration revision the change is based on. Mandatory: it is "
            "the optimistic lock that stops two clients losing each other's edits."
        )
    )
    values: dict[str, str] = Field(min_length=1)


class AddHeaterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    id: str
    power_kw: float
    full_charge_hours: float
    full_discharge_hours: float = Field(gt=0, default=10.0)
    static_emission_percent: float = Field(ge=0, le=100, default=20.0)
    name: str | None = None
    model: str | None = None
    priority: int = 0
    enabled: bool = True
    telemetry_topic: str | None = None
    output: str = "simulated"
    pin: int | None = None
    active_high: bool = True
    room_thermal_capacity_kwh_per_c: float = Field(gt=0, default=2.5)
    room_heat_loss_kw_per_c: float = Field(ge=0, default=0.12)
    temperature_targets: list[TemperatureTargetRequest] = Field(default_factory=list)


class UpdateHeaterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    name: str
    model: str | None = None
    power_kw: float = Field(gt=0)
    full_charge_hours: float = Field(gt=0)
    full_discharge_hours: float = Field(gt=0, default=10.0)
    static_emission_percent: float = Field(ge=0, le=100, default=20.0)
    priority: int = 0
    enabled: bool = True
    telemetry_topic: str | None = None
    output: str = "simulated"
    pin: int | None = None
    active_high: bool = True
    room_thermal_capacity_kwh_per_c: float = Field(gt=0, default=2.5)
    room_heat_loss_kw_per_c: float = Field(ge=0, default=0.12)
    temperature_targets: list[TemperatureTargetRequest] | None = None


class ChangeResponse(BaseModel):
    entity: str
    entity_key: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    action: str
    revision_before: int
    revision_after: int


class ChangesResponse(BaseModel):
    changes: list[ChangeResponse]

# --------------------------------------------------------------------------- #
# Relay test (nullable physical confirmation is deliberate).
class RelayTestStartResponse(BaseModel):
    session_id: str
    client_credential: str
    status: str
    lease_expires_at: datetime
    state_poll_seconds: float = 1
    lease_renew_seconds: float = 5

class RelayTestCommandRequest(BaseModel):
    state: bool

class RelayTestCommandResponse(BaseModel):
    heater_id: str
    desired_state: bool
    result: str
    command_seq: int


class RelayTestSessionView(BaseModel):
    id: str
    status: str
    owner: bool = False
    requested_at: datetime
    activated_at: datetime | None = None
    ended_at: datetime | None = None
    lease_expires_at: datetime | None = None
    end_reason: str | None = None


class RelayTestControllerView(BaseModel):
    state_is_current: bool
    last_seen_at: datetime | None = None


class RelayTestSafetyView(BaseModel):
    automatic_control_blocked: bool
    fault_latched: bool
    fault_session_id: str | None = None
    fault_reason: str | None = None
    fault_latched_at: datetime | None = None
    fault_recovery_attempted_at: datetime | None = None
    fault_recovered_at: datetime | None = None


class RelayTestAuditView(BaseModel):
    degraded: bool
    degraded_since: datetime | None = None


class RelayTestHeaterView(BaseModel):
    id: str
    name: str
    position: int
    power_w: int
    desired_state: bool
    confirmed_state: bool | None = None
    result: str
    result_code: str | None = None
    confirmed_at: datetime | None = None


class RelayTestView(BaseModel):
    session: RelayTestSessionView | None = None
    controller: RelayTestControllerView
    safety: RelayTestSafetyView
    audit: RelayTestAuditView
    state_poll_seconds: float = 1
    lease_renew_seconds: float = 5
    heaters: list[RelayTestHeaterView] = Field(default_factory=list)


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
    source: str = "legacy"
    status: str | None = None
    reason: str | None = None
    active: bool | None = None


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
    availability: str = "available"


class RelayTestHistoryItem(BaseModel):
    id: int
    session_id: str
    kind: str
    heater_id: str | None = None
    requested_state: bool | None = None
    result: str
    code: str | None = None
    occurred_at: datetime


class RelayTestHistoryPage(BaseModel):
    items: list[RelayTestHistoryItem]
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


PlanningResponse.model_rebuild()


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
    "PlanningForecastView",
    "PlanningCheckView",
    "PlanningPreviewJobResponse",
    "PlanningResponse",
    "WeatherRefreshResponse",
    "PlanningPlanView",
    "PlanningSlotView",
    "PlanningHeaterView",
    "PlanningDeficitView",
    "ChargeTelemetryView",
    "TemperatureTargetRequest",
    "TemperatureTargetView",
    "PlanningPreviewRequest",
    "PlanningActivateRequest",
    "HeaterChargeConfigRequest",
    "PlanningSiteConfigRequest",
    "PlanningSiteConfigResponse",
    "HourlyForecastPointView",
    "PowerSnapshot",
    "PruneResponse",
    "RelayTestHistoryPage",
    "SetFieldRequest",
    "PatchInstallationRequest",
    "ChangesResponse",
    "UpdateHeaterRequest",
    "StatusResponse",
    "TransitionPage",
]
