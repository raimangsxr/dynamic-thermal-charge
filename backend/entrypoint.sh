#!/bin/sh
set -eu

# Initialise the shared local stores before starting any runtime process.
# `dynamic-thermal-charge db init` is idempotent and only prints the onboarding
# credential when the installation is created for the first time.
python -m dynamic_thermal_charge db init --quiet

exec "$@"
