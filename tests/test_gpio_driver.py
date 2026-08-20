from datetime import datetime

import pytest

from dynamic_thermal_charge.gpio_driver import (
    GpioDriverError,
    GpioOutputDriver,
    _require_raspberry_pi,
)
from dynamic_thermal_charge.models import OutputConfig


class FakeDevice:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.actions = []
        self.closed = False

    def on(self) -> None:
        self.actions.append("on")

    def off(self) -> None:
        self.actions.append("off")

    def close(self) -> None:
        self.closed = True


def test_initializes_outputs_off_and_honors_active_high() -> None:
    devices = []

    def factory(**kwargs):
        device = FakeDevice(**kwargs)
        devices.append(device)
        return device

    driver = GpioOutputDriver(
        {
            "salon": OutputConfig(kind="gpio", pin=17, active_high=False),
            "entrada": OutputConfig(kind="gpio", pin=18, active_high=True),
        },
        device_factory=factory,
    )

    assert devices[0].kwargs == {
        "pin": 17,
        "active_high": False,
        "initial_value": False,
    }
    assert devices[1].kwargs["active_high"] is True

    driver.set_state("salon", True, datetime(2026, 1, 1))
    driver.set_state("salon", False, datetime(2026, 1, 1))
    driver.close()

    assert devices[0].actions == ["on", "off", "off"]
    assert all(device.closed for device in devices)


def test_closes_initialized_outputs_when_later_initialization_fails() -> None:
    first = FakeDevice()

    def factory(**_kwargs):
        if not first.kwargs:
            first.kwargs = {"created": True}
            return first
        raise RuntimeError("gpio busy")

    with pytest.raises(GpioDriverError, match="failed to initialize"):
        GpioOutputDriver(
            {
                "one": OutputConfig(kind="gpio", pin=17),
                "two": OutputConfig(kind="gpio", pin=18),
            },
            device_factory=factory,
        )

    assert "off" in first.actions
    assert first.closed is True


def test_rejects_non_raspberry_pi_platform(tmp_path) -> None:
    model = tmp_path / "model"
    model.write_text("Generic Linux board\x00", encoding="utf-8")

    with pytest.raises(GpioDriverError, match="unsupported GPIO platform"):
        _require_raspberry_pi(model)


def test_accepts_raspberry_pi_model(tmp_path) -> None:
    model = tmp_path / "model"
    model.write_text("Raspberry Pi 2 Model B Rev 1.1\x00", encoding="utf-8")

    _require_raspberry_pi(model)
