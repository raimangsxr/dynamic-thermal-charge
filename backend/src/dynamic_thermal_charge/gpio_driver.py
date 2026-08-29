"""Fail-safe GPIO output driver backed by GPIO Zero and lgpio."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .models import OutputConfig


logger = logging.getLogger(__name__)


class GpioDriverError(RuntimeError):
    """GPIO initialization or output control failed."""


class DigitalOutput(Protocol):
    def on(self) -> None: ...

    def off(self) -> None: ...

    def close(self) -> None: ...


DeviceFactory = Callable[..., DigitalOutput]


class GpioOutputDriver:
    def __init__(
        self,
        outputs: Mapping[str, OutputConfig],
        device_factory: DeviceFactory | None = None,
    ) -> None:
        if not outputs:
            raise GpioDriverError("at least one GPIO output is required")
        self._devices: dict[str, DigitalOutput] = {}
        self._pin_factory: Any = None
        try:
            factory = device_factory or self._load_gpiozero_factory()
            for heater_id, output in outputs.items():
                if output.kind != "gpio" or output.pin is None:
                    raise GpioDriverError(
                        f"heater {heater_id} does not have a GPIO output"
                    )
                self._devices[heater_id] = factory(
                    pin=output.pin,
                    active_high=output.active_high,
                    initial_value=False,
                )
                logger.info(
                    "Initialized GPIO output %s on BCM %d active_high=%s (OFF)",
                    heater_id,
                    output.pin,
                    output.active_high,
                )
        except Exception as exc:
            self.close()
            if isinstance(exc, GpioDriverError):
                raise
            raise GpioDriverError(f"failed to initialize GPIO outputs: {exc}") from exc

    def set_state(self, heater_id: str, enabled: bool, at: datetime) -> None:
        try:
            device = self._devices[heater_id]
        except KeyError as exc:
            raise GpioDriverError(f"unknown GPIO output: {heater_id}") from exc
        try:
            device.on() if enabled else device.off()
        except Exception as exc:
            raise GpioDriverError(
                f"failed to set GPIO output {heater_id}={enabled}: {exc}"
            ) from exc
        logger.info("GPIO output changed: %s=%s at %s", heater_id, enabled, at)

    def close(self) -> None:
        self._close_devices()
        if self._pin_factory is not None:
            try:
                self._pin_factory.close()
            except Exception:
                logger.exception("Failed to close lgpio pin factory")
            self._pin_factory = None
        logger.info("Closed GPIO output driver")

    def _close_devices(self) -> None:
        for heater_id, device in tuple(self._devices.items()):
            try:
                device.off()
            except Exception:
                logger.exception("Failed to force GPIO output %s OFF", heater_id)
            try:
                device.close()
            except Exception:
                logger.exception("Failed to close GPIO output %s", heater_id)
        self._devices.clear()

    def _load_gpiozero_factory(self) -> DeviceFactory:
        _require_raspberry_pi()
        try:
            from gpiozero import OutputDevice
            from gpiozero.pins.lgpio import LGPIOFactory
        except ImportError as exc:
            raise GpioDriverError(
                "GPIO dependencies are missing; install the project with the gpio extra"
            ) from exc
        try:
            self._pin_factory = LGPIOFactory(chip=0)
        except Exception as exc:
            raise GpioDriverError(
                "cannot open gpiochip0; check lgpio installation and gpio permissions"
            ) from exc

        def create_device(**kwargs):
            return OutputDevice(pin_factory=self._pin_factory, **kwargs)

        return create_device


def _require_raspberry_pi(model_path: str | Path = "/proc/device-tree/model") -> None:
    try:
        model = Path(model_path).read_text(encoding="utf-8").rstrip("\x00")
    except OSError as exc:
        raise GpioDriverError("GPIO driver requires a Raspberry Pi") from exc
    if "Raspberry Pi" not in model:
        raise GpioDriverError(f"unsupported GPIO platform: {model}")
