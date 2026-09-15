#!/bin/sh
set -eu
cd /opt/app/repo

if [ ! -c /dev/gpiochip0 ]; then
    echo "ERROR: /dev/gpiochip0 is missing or is not a character device; connect the GPIO device before deploying." >&2
    exit 1
fi

if ! detected_gpio_gid=$(stat -c '%g' /dev/gpiochip0); then
    echo "ERROR: could not determine the group ID of /dev/gpiochip0; check the device and its ownership." >&2
    exit 1
fi

configured_gpio_gid=${DTC_GPIO_GID:-}
if [ -n "$configured_gpio_gid" ] && [ "$configured_gpio_gid" != "$detected_gpio_gid" ]; then
    echo "ERROR: DTC_GPIO_GID=$configured_gpio_gid does not match /dev/gpiochip0 group $detected_gpio_gid; unset it or set it to $detected_gpio_gid." >&2
    exit 1
fi
export DTC_GPIO_GID="$detected_gpio_gid"

git fetch --quiet origin main
git reset --hard --quiet origin/main
desired=$(tr -d '[:space:]' < deploy/release)
current=$(docker compose -f deploy/compose.yaml ps --format '{{.Image}}' 2>/dev/null | head -1 | sed 's/.*://') || current=
export APP_VERSION="$desired"
export DOCKERHUB_USERNAME=rromani
docker compose -f deploy/compose.yaml config --quiet

if [ "$desired" != "$current" ]; then
    echo "release update detected from=${current:-none} to=$desired"
    docker compose -f deploy/compose.yaml pull
    docker compose -f deploy/compose.yaml up -d --remove-orphans --wait --wait-timeout 120
    echo "release deployed=$desired"
else
    # Keep routine cron runs quiet while still reconciling device-group changes.
    docker compose -f deploy/compose.yaml up -d --remove-orphans --wait --wait-timeout 120 >/dev/null
fi
