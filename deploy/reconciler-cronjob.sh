#!/bin/sh
set -eu

APP_ROOT=${APP_ROOT:-/opt/app}
REPO_ROOT=${REPO_ROOT:-"$APP_ROOT/repo"}
RECONCILE_SCRIPT=${RECONCILE_SCRIPT:-"$REPO_ROOT/deploy/reconcile.sh"}
LOG_FILE=${RECONCILE_LOG:-"$APP_ROOT/reconciler.log"}
CRONTAB_BIN=${CRONTAB_BIN:-crontab}
CRON_SCRIPT=${CRON_SCRIPT:-"$REPO_ROOT/deploy/reconciler-cronjob.sh"}
CRON_MARKER='# dynamic-thermal-charge reconciler'
CRON_COMMAND="$CRON_SCRIPT run"
CRON_LINE="*/5 * * * * $CRON_COMMAND $CRON_MARKER"

timestamp() {
    date '+%Y-%m-%dT%H:%M:%S%z'
}

run_reconciler() {
    mkdir -p "$(dirname "$LOG_FILE")"

    # An unchanged release produces no output in reconcile.sh, so this loop
    # leaves the log untouched until an update or an error is reported.
    /bin/sh "$RECONCILE_SCRIPT" 2>&1 |
        while IFS= read -r line || [ -n "$line" ]; do
            printf '[%s] %s\n' "$(timestamp)" "$line"
        done >>"$LOG_FILE"
}

install_cronjob() {
    current_crontab=$("$CRONTAB_BIN" -l 2>/dev/null || true)

    if printf '%s\n' "$current_crontab" | grep -Fq "$CRON_MARKER"; then
        exit 0
    fi

    {
        if [ -n "$current_crontab" ]; then
            printf '%s\n' "$current_crontab"
        fi
        printf '%s\n' "$CRON_LINE"
    } | "$CRONTAB_BIN" -
}

case ${1:-install} in
    install)
        install_cronjob
        ;;
    run)
        run_reconciler
        ;;
    *)
        echo "usage: $0 [install|run]" >&2
        exit 2
        ;;
esac
