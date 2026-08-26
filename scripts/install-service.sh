#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="dynamic-thermal-charge"
SERVICE_USER="dynamic-thermal-charge"
INSTALL_ROOT="/opt/${SERVICE_NAME}"
CONFIG_ROOT="/etc/${SERVICE_NAME}"
STATE_ROOT="/var/lib/${SERVICE_NAME}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_GPIO=false

if [[ ${1:-} == "--with-gpio" ]]; then
  WITH_GPIO=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: sudo $0 [--with-gpio]" >&2
  exit 1
fi

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root: sudo $0" >&2
  exit 1
fi

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "python3.12 is required but was not found" >&2
  exit 1
fi

if ! getent group "${SERVICE_USER}" >/dev/null; then
  groupadd --system "${SERVICE_USER}"
fi
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${SERVICE_USER}" \
    --home-dir "${STATE_ROOT}" \
    --shell /usr/sbin/nologin \
    "${SERVICE_USER}"
fi

install -d -m 0755 -o root -g root "${INSTALL_ROOT}" "${CONFIG_ROOT}"
install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_ROOT}"

if [[ ! -x "${INSTALL_ROOT}/venv/bin/python" ]]; then
  python3.12 -m venv "${INSTALL_ROOT}/venv"
fi
if [[ ${WITH_GPIO} == true ]]; then
  apt-get update
  apt-get install -y swig liblgpio-dev
  "${INSTALL_ROOT}/venv/bin/python" -m pip install --upgrade "${PROJECT_ROOT}[db,gpio]"
  if ! getent group gpio >/dev/null; then
    echo "The gpio group is missing; cannot grant gpiochip access" >&2
    exit 1
  fi
  usermod --append --groups gpio "${SERVICE_USER}"
else
  "${INSTALL_ROOT}/venv/bin/python" -m pip install --upgrade "${PROJECT_ROOT}[db]"
fi

# Configuration now lives in a database, not in a file. A leftover config.yaml
# means this host is being upgraded from a file-based install, and its real
# configuration has to be re-entered by hand (FR-031). Seeding the example
# installation on top of that would put example data between the operator and
# the configuration they are about to reproduce, so we do not do it (FR-030).
UPGRADING_FROM_FILE=false
if [[ -e "${CONFIG_ROOT}/config.yaml" ]]; then
  UPGRADING_FROM_FILE=true
  mv "${CONFIG_ROOT}/config.yaml" "${CONFIG_ROOT}/config.yaml.pre-database"
  chmod 0640 "${CONFIG_ROOT}/config.yaml.pre-database"
  chown root:"${SERVICE_USER}" "${CONFIG_ROOT}/config.yaml.pre-database"
fi

if [[ ! -e "${CONFIG_ROOT}/environment" ]]; then
  install -m 0600 -o root -g root \
    "${PROJECT_ROOT}/deploy/environment.example" \
    "${CONFIG_ROOT}/environment"
else
  echo "Keeping existing ${CONFIG_ROOT}/environment"
fi

install -m 0644 -o root -g root \
  "${PROJECT_ROOT}/deploy/systemd/${SERVICE_NAME}.service" \
  "${UNIT_PATH}"
install -m 0644 -o root -g root \
  "${PROJECT_ROOT}/deploy/systemd/gpio.conf.example" \
  "${CONFIG_ROOT}/gpio-systemd-override.conf.example"

systemctl daemon-reload

DTC="${INSTALL_ROOT}/venv/bin/dynamic-thermal-charge"

echo
echo "Installation complete. Before starting:"
echo "  1. Set DTC_DATABASE_URL and AEMET_API_KEY in ${CONFIG_ROOT}/environment"
if [[ ${UPGRADING_FROM_FILE} == true ]]; then
  echo
  echo "  ATTENTION: this host was configured with a file. Your previous"
  echo "  configuration has been kept at:"
  echo "    ${CONFIG_ROOT}/config.yaml.pre-database"
  echo "  It is NOT migrated automatically. Create an empty database and"
  echo "  re-enter the installation by hand, checking BCM pins, active_high and"
  echo "  the power cap against that file:"
  echo "    set -a; . ${CONFIG_ROOT}/environment; set +a"
  echo "    ${DTC} db init --no-seed"
  echo "    ${DTC} config add-heater ...   # one per storage heater"
  echo "    ${DTC} config show             # verify field by field"
else
  echo "  2. Initialise the database once:"
  echo "       set -a; . ${CONFIG_ROOT}/environment; set +a"
  echo "       ${DTC} db init"
  echo "  3. Review the seeded installation: ${DTC} config show"
fi
echo
echo "  Then: systemctl start ${SERVICE_NAME}"
echo "  Enable at boot: systemctl enable ${SERVICE_NAME}"
echo
echo "The controller remains simulated; this service does not access GPIO."
if [[ ${WITH_GPIO} == true ]]; then
  echo "GPIO dependencies and group membership are ready, but real outputs remain disabled."
fi
