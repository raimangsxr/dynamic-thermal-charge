#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="dynamic-thermal-charge"
SERVICE_USER="dynamic-thermal-charge"
INSTALL_ROOT="/opt/${SERVICE_NAME}"
CONFIG_ROOT="/etc/${SERVICE_NAME}"
STATE_ROOT="/var/lib/${SERVICE_NAME}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
"${INSTALL_ROOT}/venv/bin/python" -m pip install --upgrade "${PROJECT_ROOT}"

if [[ ! -e "${CONFIG_ROOT}/config.yaml" ]]; then
  sed \
    's|state_file: ../var/active-plan.json|state_file: /var/lib/dynamic-thermal-charge/active-plan.json|' \
    "${PROJECT_ROOT}/examples/raspberry-pi.yaml" \
    >"${CONFIG_ROOT}/config.yaml"
  chmod 0640 "${CONFIG_ROOT}/config.yaml"
  chown root:"${SERVICE_USER}" "${CONFIG_ROOT}/config.yaml"
else
  echo "Keeping existing ${CONFIG_ROOT}/config.yaml"
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

systemctl daemon-reload

echo
echo "Installation complete. Before starting:"
echo "  1. Set AEMET_API_KEY in ${CONFIG_ROOT}/environment"
echo "  2. Review ${CONFIG_ROOT}/config.yaml"
echo "  3. Validate: systemctl start ${SERVICE_NAME}"
echo "  4. Enable at boot: systemctl enable ${SERVICE_NAME}"
echo
echo "The controller remains simulated; this service does not access GPIO."
