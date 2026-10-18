"""Five-minute measured history and governing-slot selection."""

from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine, insert, select

from dynamic_thermal_charge.models import ChargeTelemetry, Heater
from dynamic_thermal_charge.runtime import _measured_discharge_commands
from dynamic_thermal_charge.persistence.history import (
    SqlHistoryReader,
    SqlHistoryRecorder,
    _plan_cues,
)
from dynamic_thermal_charge.persistence.schema import (
    application_metadata,
    automatic_plan,
    automatic_plan_slot,
    measured_heater_sample,
    measured_installation_sample,
    plan_audit,
)


UTC = timezone.utc
_MISSING = object()


def _heater() -> Heater:
    return Heater(id="salon", name="Salón", power_w=2000, full_charge_minutes=60)


def _telemetry(at: datetime, *, soc: float | None = 50.0) -> ChargeTelemetry:
    return ChargeTelemetry(
        heater_id="salon",
        indoor_temperature_c=20.5,
        stored_soc_percent=soc,
        indoor_received_at=at - timedelta(minutes=1),
        stored_soc_received_at=at - timedelta(minutes=1),
        damper_position_percent=40,
        damper_received_at=at - timedelta(minutes=1),
    )


def test_sampler_floors_to_five_minutes_retains_nulls_and_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    application_metadata.create_all(engine)
    recorder = SqlHistoryRecorder(engine, installation_id=7)
    observed = datetime(2026, 1, 16, 12, 7, tzinfo=UTC)
    heater = _heater()
    recorder.record_measured(
        observed,
        heaters=(heater,),
        telemetry={"salon": _telemetry(observed, soc=50)},
        outdoor=type("Outdoor", (), {"temperature_c": 8.0, "received_at": observed})(),
        active_outputs={"salon"},
        discharge_commands={"salon": True},
    )
    # A retry in the same bucket must not overwrite the captured observation.
    recorder.record_measured(
        observed + timedelta(minutes=2),
        heaters=(heater,),
        telemetry={"salon": _telemetry(observed + timedelta(minutes=2), soc=60)},
        outdoor=None,
        active_outputs=set(),
        discharge_commands={"salon": False},
    )

    with engine.connect() as connection:
        installation = connection.execute(select(measured_installation_sample)).mappings().all()
        samples = connection.execute(select(measured_heater_sample)).mappings().all()
    assert len(installation) == 1
    assert installation[0]["observed_at"] == datetime(2026, 1, 16, 12, 5)
    assert installation[0]["outdoor_temperature_c"] == 8.0
    assert len(samples) == 1
    assert samples[0]["stored_soc_percent"] == 50
    assert samples[0]["stored_energy_kwh"] == 1
    assert samples[0]["confirmed_charge_power_w"] == 2000
    assert samples[0]["discharge_commanded"] is True

    stale = observed + timedelta(minutes=5)
    recorder.record_measured(
        stale,
        heaters=(heater,),
        telemetry={"salon": _telemetry(stale - timedelta(minutes=16), soc=55)},
        outdoor=None,
        active_outputs=set(),
        discharge_commands=None,
    )
    with engine.connect() as connection:
        row = connection.execute(
            select(measured_heater_sample).where(measured_heater_sample.c.observed_at == datetime(2026, 1, 16, 12, 10))
        ).mappings().one()
    assert row["indoor_temperature_c"] is None
    assert row["stored_soc_percent"] is None
    assert row["discharge_commanded"] is None
    engine.dispose()


def test_sampler_persists_the_effective_calibration_discharge_command():
    engine = create_engine("sqlite:///:memory:")
    application_metadata.create_all(engine)
    observed = datetime(2026, 1, 16, 12, 7, tzinfo=UTC)
    heater = _heater()
    plan = {
        "status": "VALID",
        "slots": [
            {
                "start": observed.replace(minute=5),
                "end": observed.replace(minute=35),
                "target_temperature_c": {"salon": 21.0},
                "heat_delivered_kwh": {"salon": 0.1},
            }
        ],
    }
    commands = _measured_discharge_commands(
        ("salon",),
        plan=plan,
        at=observed,
        topic_prefix="telemetria",
        automatic_control_enabled=True,
        heater_modes={},
        relay_test_in_progress=False,
        calibration_projection={
            "salon": {
                "commands": {
                    "discharge": False,
                    "authorized_at": observed.isoformat(),
                }
            }
        },
    )
    assert commands[0].enabled is False

    recorder = SqlHistoryRecorder(engine, installation_id=7)
    recorder.record_measured(
        observed,
        heaters=(heater,),
        telemetry={"salon": _telemetry(observed)},
        outdoor=None,
        active_outputs=set(),
        discharge_commands=commands,
    )

    with engine.connect() as connection:
        row = connection.execute(select(measured_heater_sample)).mappings().one()
    assert row["discharge_commanded"] is False
    engine.dispose()


def test_series_keeps_the_started_slot_on_the_previous_plan():
    engine = create_engine("sqlite:///:memory:")
    application_metadata.create_all(engine)
    start = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(measured_installation_sample),
            [
                {"installation_id": 7, "observed_at": start + timedelta(minutes=5), "outdoor_temperature_c": 8},
                {"installation_id": 7, "observed_at": start + timedelta(minutes=35), "outdoor_temperature_c": 7},
            ],
        )
        connection.execute(
            insert(measured_heater_sample),
            [
                {"installation_id": 7, "heater_id": "salon", "observed_at": start + timedelta(minutes=5), "indoor_temperature_c": 20, "stored_soc_percent": 50, "stored_energy_kwh": 1, "confirmed_charge_power_w": 2000, "discharge_commanded": False, "damper_position_percent": 30},
                {"installation_id": 7, "heater_id": "salon", "observed_at": start + timedelta(minutes=35), "indoor_temperature_c": 20.2, "stored_soc_percent": 55, "stored_energy_kwh": 1.1, "confirmed_charge_power_w": 0, "discharge_commanded": True, "damper_position_percent": 35},
            ],
        )
        plan_rows = []
        slot_rows = []
        audit_rows = []
        for plan_id, activation in ((1, start - timedelta(minutes=20)), (2, start + timedelta(minutes=12))):
            plan_rows.append({
                "id": plan_id,
                "installation_id": 7,
                "configuration_revision": 1,
                "constraints_revision": 1,
                "forecast_id": None,
                "horizon_start": start,
                "horizon_end": start + timedelta(hours=1),
                "slot_minutes": 30,
                "status": "VALID",
                "reason": "periodic",
                "input_token": f"plan-{plan_id}",
                "score_json": "[]",
                "deficits_json": "[]",
                "inputs_json": json.dumps({
                    "activation_mode": "automatic",
                    "evidence": {"limits": {"contracted_power_w": 2000}},
                    "explanations": [{
                        "heater_id": "salon",
                        "charge_reasons": [
                            {
                                "start": start.isoformat(),
                                "end": (start + timedelta(minutes=30)).isoformat(),
                                "reason": "first",
                            },
                            {
                                "start": (start + timedelta(minutes=30)).isoformat(),
                                "end": (start + timedelta(hours=1)).isoformat(),
                                "reason": "second",
                            },
                        ],
                    }],
                }),
                "active": plan_id == 2,
                "created_at": activation,
            })
            for slot_start in (start, start + timedelta(minutes=30)):
                slot_rows.append({
                    "plan_id": plan_id,
                    "slot_start": slot_start,
                    "slot_end": slot_start + timedelta(minutes=30),
                    "heater_ids_json": '["salon"]',
                    "power_w": 2000 if plan_id == 2 else 1000,
                    "stored_charge_json": '{"salon": 60}',
                    "required_charge_json": '{}',
                    "outdoor_temperature_c": 6 if plan_id == 2 else 8,
                    "initial_soc_json": '{}',
                    "demand_json": '{}',
                    "heater_power_json": '{"salon": 2000}',
                    "stored_energy_json": '{"salon": 1.2}',
                    "indoor_temperature_json": '{"salon": 21}',
                    "target_temperature_json": '{"salon": 21}',
                    "heat_delivered_json": '{"salon": 0.1}',
                    "thermal_loss_json": '{}',
                    "temperature_shortfall_json": '{}',
                    "charge_energy_json": '{}',
                    "heat_limit_json": '{}',
                    "forced_heat_json": '{}',
                })
            audit_rows.append({"installation_id": 7, "plan_id": plan_id, "event": "activated", "reason": "periodic", "details_json": "{}", "occurred_at": activation})
        connection.execute(insert(automatic_plan), plan_rows)
        connection.execute(insert(automatic_plan_slot), slot_rows)
        connection.execute(insert(plan_audit), audit_rows)

    page = SqlHistoryReader(engine, installation_id=7).series(
        start + timedelta(minutes=5),
        start + timedelta(minutes=35),
        scope="heater",
        heater_id="salon",
    )
    assert [item["governing_plan"]["plan_id"] for item in page.items] == [1, 2]
    assert page.items[0]["governing_plan"]["slot_start"] == start
    assert page.items[1]["projected"]["outdoor_temperature_c"] == 6
    assert [
        [reason["reason"] for reason in item["cues"]["charge_reasons"]]
        for item in page.items
    ] == [["first"], ["second"]]
    first = SqlHistoryReader(engine, installation_id=7).series(
        start + timedelta(minutes=5),
        start + timedelta(minutes=35),
        scope="heater",
        heater_id="salon",
        limit=1,
    )
    assert first.has_more is True
    second = SqlHistoryReader(engine, installation_id=7).series(
        start + timedelta(minutes=5),
        start + timedelta(minutes=35),
        scope="heater",
        heater_id="salon",
        limit=1,
        cursor=first.next_cursor,
    )
    assert [item["at"] for item in second.items] == [start + timedelta(minutes=35)]
    engine.dispose()


def test_series_cues_preserve_null_and_explicit_empty_charge_reasons():
    start = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    slot = {"slot_start": start, "slot_end": start + timedelta(minutes=30)}

    def cues(charge_reasons: object) -> object:
        explanation = {"heater_id": "salon"}
        if charge_reasons is not _MISSING:
            explanation["charge_reasons"] = charge_reasons
        return _plan_cues(
            {"explanations": [explanation]},
            slot,
            at=start + timedelta(minutes=5),
            heater_id="salon",
        )["charge_reasons"]

    assert cues(_MISSING) is None
    assert cues(None) is None
    assert cues([]) == []
    assert cues([
        {
            "start": start - timedelta(hours=1),
            "end": start - timedelta(minutes=30),
            "reason": "outside",
        }
    ]) == []
