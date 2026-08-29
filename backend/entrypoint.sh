#!/bin/sh
set -eu

# Initialise the shared local stores before starting any runtime process.
# `DTC_API_TOKEN` is persisted as the administrator token on first startup, so
# the panel can use its normal login without a separate onboarding credential.
: "${DTC_API_TOKEN:?set DTC_API_TOKEN in /etc/app/app.env}"
python -m dynamic_thermal_charge db init --quiet --admin-token-env DTC_API_TOKEN

exec "$@"
