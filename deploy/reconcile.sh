#!/bin/sh
set -eu
cd /opt/app/repo
git fetch --quiet origin main
git reset --hard --quiet origin/main
desired=$(tr -d '[:space:]' < deploy/release)
current=$(docker compose -f deploy/compose.yaml ps --format '{{.Image}}' 2>/dev/null | head -1 | sed 's/.*://') || current=
echo "release detected=$desired deployed=${current:-none}"
[ "$desired" = "$current" ] && exit 0
export APP_VERSION="$desired"
export DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?set DOCKERHUB_USERNAME}"
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml pull
docker compose -f deploy/compose.yaml up -d --remove-orphans --wait
echo "release deployed=$desired"
