from datetime import date, datetime
import logging

from dynamic_thermal_charge.cli import _run_watchdog
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.models import WeatherWatchdogConfig
from dynamic_thermal_charge.watchdog import ForecastWatchdog
from dynamic_thermal_charge.weather import OutdoorForecast


def forecast(source: str, temperature: float = 8) -> OutdoorForecast:
    return OutdoorForecast(
        date=date(2026, 1, 15),
        average_temperature_c=temperature,
        minimum_temperature_c=temperature - 3,
        maximum_temperature_c=temperature + 3,
        source=source,
        location="Noia, A Coruña" if source == "aemet" else None,
    )


class SequenceProvider:
    def __init__(self, forecasts):
        self._forecasts = iter(forecasts)

    def forecast_for(self, forecast_date):
        return next(self._forecasts)


def test_retries_quickly_in_degraded_mode_and_refreshes_after_recovery(
    caplog,
) -> None:
    watchdog = ForecastWatchdog(
        SequenceProvider([forecast("simulated"), forecast("aemet", 7)]),
        expected_source="aemet",
        config=WeatherWatchdogConfig(retry_minutes=10, refresh_minutes=120),
    )

    with caplog.at_level(logging.INFO):
        degraded = watchdog.poll(date(2026, 1, 15))
        recovered = watchdog.poll(date(2026, 1, 15))

    assert degraded.degraded is True
    assert degraded.next_poll_seconds == 600
    assert recovered.degraded is False
    assert recovered.next_poll_seconds == 7200
    assert "entered degraded mode" in caplog.text
    assert "recovered primary forecast provider" in caplog.text


def test_watchdog_mode_builds_fallback_plan_before_waiting(capsys) -> None:
    config = example_installation()

    def stop_after_first_cycle(_seconds):
        raise KeyboardInterrupt

    status = _run_watchdog(
        config,
        explicit_start=datetime(2026, 1, 15),
        provider=SequenceProvider([forecast("simulated")]),
        wait=stop_after_first_cycle,
    )

    assert status == 0
    assert "Charge plan" in capsys.readouterr().out
