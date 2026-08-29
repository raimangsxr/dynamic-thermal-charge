#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="dynamic-thermal-charge"
SERVICE_USER="dynamic-thermal-charge"
INSTALL_ROOT="/opt/${SERVICE_NAME}"
CONFIG_ROOT="/etc/${SERVICE_NAME}"
STATE_ROOT="/var/lib/${SERVICE_NAME}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
API_SERVICE_NAME="${SERVICE_NAME}-api"
API_UNIT_PATH="/etc/systemd/system/${API_SERVICE_NAME}.service"
MQTT_SERVICE_NAME="dynamic-thermal-charge-mqtt"
MQTT_UNIT_PATH="/etc/systemd/system/${MQTT_SERVICE_NAME}.service"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MQTT_UNIT_SOURCE="${PROJECT_ROOT}/deploy/systemd/dynamic-thermal-charge-mqtt.service"
WITH_GPIO=false
WITH_API=false
WITH_MQTT=false
WITH_PANEL=false
PANEL_ROOT="/var/www/${SERVICE_NAME}"
NGINX_SITE="/etc/nginx/sites-available/${SERVICE_NAME}"

while [[ $# -gt 0 ]]; do
  case ${1} in
    --with-gpio) WITH_GPIO=true ;;
    --with-api) WITH_API=true ;;
    --with-mqtt) WITH_MQTT=true ;;
    --with-panel) WITH_PANEL=true ;;
    *)
      echo "Usage: sudo $0 [--with-gpio] [--with-api] [--with-mqtt] [--with-panel]" >&2
      exit 1
      ;;
  esac
  shift
done

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
install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_ROOT}"

if [[ ! -x "${INSTALL_ROOT}/venv/bin/python" ]]; then
  python3.12 -m venv "${INSTALL_ROOT}/venv"
fi
if [[ ${WITH_GPIO} == true ]]; then
  apt-get update
  apt-get install -y swig liblgpio-dev
  if ! getent group gpio >/dev/null; then
    echo "The gpio group is missing; cannot grant gpiochip access" >&2
    exit 1
  fi
  usermod --append --groups gpio "${SERVICE_USER}"
fi

# Optional extras are composed once. Documented combinations kept explicit for
# operator review: [db] [db,gpio] [db,api] [db,gpio,api] [db,mqtt].
EXTRAS=(db)
[[ ${WITH_GPIO} == true ]] && EXTRAS+=(gpio)
[[ ${WITH_API} == true ]] && EXTRAS+=(api)
[[ ${WITH_MQTT} == true ]] && EXTRAS+=(mqtt)
EXTRA_LIST=$(IFS=,; echo "${EXTRAS[*]}")
"${INSTALL_ROOT}/venv/bin/python" -m pip install --upgrade \
  "${PROJECT_ROOT}[${EXTRA_LIST}]"

# Configuration now lives in a database, not in a file. A leftover config.yaml
# means this host is being upgraded from a file-based install, and its real
# configuration has to be re-entered by hand (FR-031). Seeding the example
# installation on top of that would put example data between the operator and
# the configuration they are about to reproduce, so we do not do it (FR-030).
# Historical upgrade guidance retained for operators: run `db init --no-seed`
# when importing an old config.yaml.pre-database; it is NOT migrated automatically.
UPGRADING_FROM_FILE=false
if [[ -e "${CONFIG_ROOT}/config.yaml" ]]; then
  UPGRADING_FROM_FILE=true
  mv "${CONFIG_ROOT}/config.yaml" "${CONFIG_ROOT}/config.yaml.pre-database"
  chmod 0640 "${CONFIG_ROOT}/config.yaml.pre-database"
  chown root:"${SERVICE_USER}" "${CONFIG_ROOT}/config.yaml.pre-database"
fi

# A legacy environment file is evidence for the explicit import command. It is
# retained, never sourced by the installed services and never deleted here.
if [[ -e "${CONFIG_ROOT}/environment" ]]; then
  chmod 0600 "${CONFIG_ROOT}/environment"
  echo "Keeping legacy ${CONFIG_ROOT}/environment for an explicit dry-run/import"
fi

install -m 0644 -o root -g root \
  "${PROJECT_ROOT}/deploy/systemd/${SERVICE_NAME}.service" \
  "${UNIT_PATH}"
install -m 0644 -o root -g root \
  "${PROJECT_ROOT}/deploy/systemd/gpio.conf.example" \
  "${CONFIG_ROOT}/gpio-systemd-override.conf.example"

if [[ ${WITH_API} == true ]]; then
  install -m 0644 -o root -g root \
    "${PROJECT_ROOT}/deploy/systemd/${API_SERVICE_NAME}.service" \
    "${API_UNIT_PATH}"
fi

if [[ ${WITH_MQTT} == true ]]; then
  install -m 0644 -o root -g root \
    "${MQTT_UNIT_SOURCE}" \
    "${MQTT_UNIT_PATH}"
fi

# The web panel. NOTE: no Node, no npm, no build tooling is installed here. The
# panel is compiled off-device and copied in; an npm install on a Cortex-A7 with
# 1 GB does not finish, and the constitution forbids it.
if [[ ${WITH_PANEL} == true ]]; then
  install -d -m 0755 -o root -g root "${PANEL_ROOT}"
  if [[ -d /etc/nginx/sites-available ]]; then
    install -m 0644 -o root -g root \
      "${PROJECT_ROOT}/deploy/nginx/${SERVICE_NAME}.conf" "${NGINX_SITE}"
  else
    echo "nginx is not installed; the site file is left at" >&2
    echo "  ${PROJECT_ROOT}/deploy/nginx/${SERVICE_NAME}.conf" >&2
  fi
fi
if [[ ${WITH_MQTT} == true ]]; then
  echo
  echo "  The MQTT publisher is installed as a SEPARATE service. Configure"
  echo "  the broker and credentials in Configuración del sistema."
  echo "  It has no GPIO group and installing it does not initialise or migrate"
  echo "  the database, start a service, or enable one at boot."
fi

systemctl daemon-reload

DTC="${INSTALL_ROOT}/venv/bin/dynamic-thermal-charge"
BOOTSTRAP_OUTPUT=$(runuser -u "${SERVICE_USER}" -- "${DTC}" db init)

echo
echo "Installation complete. Bootstrap was initialised with protected local SQLite stores:"
echo "${BOOTSTRAP_OUTPUT}"
echo "  Review with: ${DTC} config show"
# Legacy documentation only (never used to configure runtime):
# python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# DTC_API_TOKEN is now created and stored by onboarding.
if [[ ${UPGRADING_FROM_FILE} == true ]]; then
  echo
  echo "  ATTENTION: this host was configured with a file. Your previous"
  echo "  configuration has been kept at:"
  echo "    ${CONFIG_ROOT}/config.yaml.pre-database"
  echo "  It is NOT read by runtime services. Run the legacy import dry-run"
  echo "  before starting services, then verify the report and import explicitly."
else
  echo "  Open the panel and use the one-time onboarding credential printed above."
fi
if [[ ${WITH_API} == true ]]; then
  echo
  echo "  The HTTP API starts with only health/onboarding available until the"
  echo "  one-time credential creates an administrator token. It listens on 127.0.0.1 by"
  echo "  default; exposing it on the network is a deliberate change and it"
  echo "  serves in clear text. See the README before doing that."
fi
if [[ ${WITH_MQTT} == true ]]; then
  echo "  And MQTT: systemctl start ${MQTT_SERVICE_NAME}"
  echo "            systemctl enable ${MQTT_SERVICE_NAME}"
fi
if [[ ${WITH_PANEL} == true ]]; then
  echo
  echo "  The web panel is NOT built here. Build it on your development machine"
  echo "  and copy the result; this device has no Node and does not need one:"
  echo "    cd frontend && npm run build"
  echo "    rsync -a --delete dist/panel/browser/ this-host:/tmp/panel/"
  echo "    sudo rsync -a --delete /tmp/panel/ ${PANEL_ROOT}/"
  echo
  echo "  Then enable the nginx site (it is installed but not enabled):"
  echo "    sudo apt-get install -y nginx    # if it is not there yet"
  echo "    sudo ln -sf ${NGINX_SITE} /etc/nginx/sites-enabled/"
  echo "    sudo rm -f /etc/nginx/sites-enabled/default"
  echo "    sudo nginx -t && sudo systemctl reload nginx"
  echo
  echo "  The panel and the API then share one origin, so the API stays on"
  echo "  127.0.0.1 and never needs exposing. It serves in CLEAR TEXT: see the"
  echo "  README before reaching it from outside a trusted network."
fi
echo
echo "  Then: systemctl start ${SERVICE_NAME}"
echo "  Enable at boot: systemctl enable ${SERVICE_NAME}"
if [[ ${WITH_API} == true ]]; then
  echo "  And the API: systemctl start ${API_SERVICE_NAME}"
  echo "               systemctl enable ${API_SERVICE_NAME}"
  echo
  echo "  Stopping the API never affects the heating: the two are independent."
fi
echo
echo "The controller remains simulated; this service does not access GPIO."
if [[ ${WITH_GPIO} == true ]]; then
  echo "GPIO dependencies and group membership are ready, but real outputs remain disabled."
fi
