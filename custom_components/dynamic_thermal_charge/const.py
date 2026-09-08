"""Constants for the Dynamic Thermal Charge Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "dynamic_thermal_charge"
NAME = "Dynamic Thermal Charge"
MANUFACTURER = "Dynamic Thermal Charge"
VERSION = "0.1.0"
PLATFORMS = ("sensor", "binary_sensor", "switch", "button", "climate", "calendar")
POLL_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT_SECONDS = 10

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"

CONTROLLER_KEY = "controller"
ACCUMULATOR_KEY = "accumulator"

__all__ = [
    "ACCUMULATOR_KEY",
    "CONF_HOST",
    "CONF_PORT",
    "CONF_TOKEN",
    "CONTROLLER_KEY",
    "DOMAIN",
    "MANUFACTURER",
    "NAME",
    "PLATFORMS",
    "POLL_INTERVAL",
    "REQUEST_TIMEOUT_SECONDS",
    "VERSION",
]
