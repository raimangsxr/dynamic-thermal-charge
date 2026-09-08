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
CONFIG_ENTRY_VERSION = 2
SUPPORTED_PROTOCOLS = ("http", "https")

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
# ``protocol`` is deliberately kept separate from host and port.  The alias is
# useful to callers that describe the same field as a URL scheme.
CONF_PROTOCOL = "protocol"
CONF_SCHEME = CONF_PROTOCOL

CONTROLLER_KEY = "controller"
ACCUMULATOR_KEY = "accumulator"

__all__ = [
    "ACCUMULATOR_KEY",
    "CONFIG_ENTRY_VERSION",
    "CONF_HOST",
    "CONF_PORT",
    "CONF_PROTOCOL",
    "CONF_SCHEME",
    "CONF_TOKEN",
    "CONTROLLER_KEY",
    "DOMAIN",
    "MANUFACTURER",
    "NAME",
    "PLATFORMS",
    "POLL_INTERVAL",
    "REQUEST_TIMEOUT_SECONDS",
    "SUPPORTED_PROTOCOLS",
    "VERSION",
]
