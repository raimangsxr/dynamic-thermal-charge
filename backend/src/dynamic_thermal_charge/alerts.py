"""Operator alerts: the catalogue, the episode rule and the SMTP delivery.

An alert is raised where the condition is observed and delivered later, from a
durable queue.  That separation is the point: the conditions worth an alert are
exactly the ones where the installation is already degraded, so the notification
must survive a restart and must never be able to stall the loop that observes
it.

Nothing here reads configuration or the database directly; the repository and
the settings arrive as collaborators, which keeps the episode rule and the
message bodies testable without a broker, a mail server or a store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Callable, Mapping, Protocol, Sequence

from .system_settings import EmailSystemSettings


logger = logging.getLogger(__name__)


PLAN_RECALCULATION_INVALID = "plan_recalculation_invalid"
PLAN_RECALCULATION_DEGRADED = "plan_recalculation_degraded"

# Retries stop here: a mail server that refused five times with growing waits
# is not going to accept the sixth attempt inside the same episode.
MAX_ATTEMPTS = 5
FIRST_RETRY_SECONDS = 60


@dataclass(frozen=True)
class AlertType:
    """One catalogue entry.  Adding an alert is adding one of these."""

    name: str
    title: str
    description: str


ALERT_TYPES: tuple[AlertType, ...] = (
    AlertType(
        name=PLAN_RECALCULATION_INVALID,
        title="Replanificación imposible",
        description=(
            "Un recálculo devolvió un resultado inválido. Avisa cuando la "
            "instalación se queda sin plan activo y cuando se conserva el plan "
            "anterior por no poder reemplazarlo."
        ),
    ),
    AlertType(
        name=PLAN_RECALCULATION_DEGRADED,
        title="Replanificación degradada",
        description=(
            "Un recálculo no demostró una solución activable. El último plan "
            "válido o convergente se conserva mientras tenga horizonte vigente."
        ),
    ),
)

ALERT_TYPES_BY_NAME: Mapping[str, AlertType] = {item.name: item for item in ALERT_TYPES}


@dataclass(frozen=True)
class PendingAlert:
    """A queued message, as the delivery step reads it back."""

    id: int
    alert_type: str
    subject: str
    body: str
    attempts: int


class AlertRepository(Protocol):
    """The durable half: the queue, the episode latch and the catalogue."""

    def type_enabled(self, alert_type: str) -> bool: ...

    def episode_active(self, alert_type: str) -> bool: ...

    def open_episode(
        self, alert_type: str, *, subject: str, body: str, at: datetime
    ) -> bool: ...

    def set_episode(self, alert_type: str, *, active: bool, at: datetime) -> None: ...

    def enqueue(
        self, alert_type: str, *, subject: str, body: str, at: datetime
    ) -> int: ...

    def due(self, at: datetime, limit: int = 10) -> Sequence[PendingAlert]: ...

    def mark_sent(self, delivery_id: int, at: datetime) -> None: ...

    def mark_attempt_failed(
        self,
        delivery_id: int,
        *,
        attempts: int,
        next_attempt_at: datetime | None,
        error: str,
    ) -> None: ...


class AlertSender(Protocol):
    def send(self, settings: EmailSystemSettings, alert: PendingAlert) -> None: ...


class SmtpAlertSender:
    """Deliver one message with the standard library, credentials optional."""

    def __init__(self, credentials: Callable[[], tuple[str | None, str | None]]) -> None:
        self._credentials = credentials

    def send(self, settings: EmailSystemSettings, alert: PendingAlert) -> None:
        message = EmailMessage()
        message["From"] = settings.sender or ""
        message["To"] = ", ".join(settings.recipients)
        message["Subject"] = alert.subject
        message.set_content(alert.body)
        username, password = self._credentials()
        host = (settings.host or "").strip()
        try:
            if settings.security == "tls":
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    host, settings.port, timeout=settings.timeout_seconds
                )
            else:
                client = smtplib.SMTP(
                    host, settings.port, timeout=settings.timeout_seconds
                )
            with client:
                if settings.security == "starttls":
                    client.starttls()
                if username and password:
                    client.login(username, password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise AlertDeliveryError(str(exc)) from exc


class AlertDeliveryError(RuntimeError):
    """Any failure of the mail transport, translated at this boundary."""


class AlertService:
    """Raise alerts by episode and drain the queue with growing waits."""

    def __init__(
        self,
        repository: AlertRepository,
        *,
        settings: Callable[[], EmailSystemSettings],
        sender: AlertSender,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._sender = sender
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_attempts = max_attempts
        self._reported_unconfigured = False

    def raise_alert(self, alert_type: str, *, subject: str, body: str) -> bool:
        """Queue an alert unless its episode is already open.

        Returns whether anything was queued.  A disabled alert or an
        unconfigured mail server never opens an episode, so enabling either
        later still notifies the next occurrence.
        """
        if alert_type not in ALERT_TYPES_BY_NAME:
            raise ValueError(f"unknown alert type {alert_type!r}")
        settings = self._settings()
        if not settings.deliverable:
            if not self._reported_unconfigured:
                logger.warning(
                    "Alert %s was not queued: email alerts are disabled or "
                    "incompletely configured",
                    alert_type,
                )
                self._reported_unconfigured = True
            return False
        self._reported_unconfigured = False
        if not self._repository.type_enabled(alert_type):
            logger.debug("Alert %s is disabled in the catalogue", alert_type)
            return False
        now = self._clock()
        if not self._repository.open_episode(
            alert_type, subject=subject, body=body, at=now
        ):
            logger.debug("Alert %s already has an open episode", alert_type)
            return False
        logger.info("Alert %s queued for delivery", alert_type)
        return True

    def clear_alert(self, alert_type: str) -> None:
        """Rearm an alert: the next occurrence is a new episode."""
        if alert_type not in ALERT_TYPES_BY_NAME:
            raise ValueError(f"unknown alert type {alert_type!r}")
        if self._repository.episode_active(alert_type):
            self._repository.set_episode(
                alert_type, active=False, at=self._clock()
            )
            logger.info("Alert %s resolved and rearmed", alert_type)

    def deliver_pending(self, limit: int = 10) -> int:
        """Send what is due.  Returns how many messages were delivered."""
        settings = self._settings()
        if not settings.deliverable:
            return 0
        now = self._clock()
        delivered = 0
        for alert in self._repository.due(now, limit):
            attempts = alert.attempts + 1
            try:
                self._sender.send(settings, alert)
            except AlertDeliveryError as exc:
                exhausted = attempts >= self._max_attempts
                self._repository.mark_attempt_failed(
                    alert.id,
                    attempts=attempts,
                    next_attempt_at=(
                        None if exhausted else now + _backoff(attempts)
                    ),
                    error=str(exc)[:512],
                )
                if exhausted:
                    logger.error(
                        "Alert %s could not be delivered after %d attempts: %s",
                        alert.alert_type,
                        attempts,
                        exc,
                    )
                else:
                    logger.warning(
                        "Attempt %d to deliver alert %s failed: %s",
                        attempts,
                        alert.alert_type,
                        exc,
                    )
                continue
            self._repository.mark_sent(alert.id, now)
            delivered += 1
            logger.info("Alert %s delivered", alert.alert_type)
        return delivered

    def send_test_message(self, subject: str, body: str) -> None:
        """Validate the live configuration without touching the catalogue."""
        settings = self._settings()
        if not settings.deliverable:
            raise AlertDeliveryError(
                "email alerts are disabled or incompletely configured"
            )
        self._sender.send(
            settings,
            PendingAlert(
                id=0, alert_type="test", subject=subject, body=body, attempts=0
            ),
        )


def build_alert_service(store) -> "AlertService | None":
    """Wire an alert service from a store, or nothing if it cannot hold alerts.

    Duck-typed on purpose: the controller process and the API build the same
    service without this module importing persistence.
    """
    repository = getattr(store, "alerts", None)
    system_configuration = getattr(store, "system_configuration", None)
    if repository is None or system_configuration is None:
        return None

    def settings() -> EmailSystemSettings:
        return system_configuration.current().configuration.email

    def credentials() -> tuple[str | None, str | None]:
        secrets = system_configuration.current().secrets
        username = secrets.get("smtp_username")
        password = secrets.get("smtp_password")
        return (
            None if username is None else username.value,
            None if password is None else password.value,
        )

    return AlertService(
        repository, settings=settings, sender=SmtpAlertSender(credentials)
    )


def _backoff(attempts: int) -> timedelta:
    """One minute, then doubling: 1, 2, 4, 8 minutes."""
    return timedelta(seconds=FIRST_RETRY_SECONDS * (2 ** (attempts - 1)))


def plan_recalculation_invalid_message(
    *,
    installation: str,
    at: datetime,
    reason: str,
    detail: str,
    previous_plan_preserved: bool,
) -> tuple[str, str]:
    """Build the subject and body of the first catalogue alert."""
    consequence = (
        "Se conserva el plan anterior, que sigue ejecutándose."
        if previous_plan_preserved
        else "La instalación se queda sin plan activo hasta el próximo recálculo válido."
    )
    subject = f"[{installation}] Replanificación imposible"
    body = "\n".join(
        (
            f"Instalación: {installation}",
            f"Momento: {at.isoformat()}",
            f"Causa: {reason}",
            f"Detalle: {detail}",
            "",
            consequence,
        )
    )
    return subject, body


def plan_recalculation_degraded_message(
    *,
    installation: str,
    at: datetime,
    plan: Any,
    retained_horizon_end: datetime | None,
) -> tuple[str, str]:
    """Build the durable alert for a non-activable recalculation candidate."""
    violations = tuple(getattr(plan, "violations", ()) or ())
    heaters = sorted({item.heater_id for item in violations if item.heater_id})
    windows = sorted(
        {
            f"{item.target_window_start.isoformat()}–{item.target_window_end.isoformat()}"
            for item in violations
            if getattr(item, "target_window_start", None) is not None
            and getattr(item, "target_window_end", None) is not None
        }
    )
    causes = sorted({str(item.reason) for item in violations})
    deficits = [
        float(item.shortfall)
        for item in violations
        if getattr(item, "shortfall", None) is not None
    ]
    maximum = max(deficits, default=None)
    remaining = (
        retained_horizon_end.isoformat()
        if retained_horizon_end is not None
        else "no disponible"
    )
    subject = f"[{installation}] Replanificación degradada"
    body = "\n".join(
        (
            f"Instalación: {installation}",
            f"Momento: {at.isoformat()}",
            f"Acumuladores afectados: {', '.join(heaters) or 'no determinado'}",
            f"Consignas afectadas: {', '.join(windows) or 'no determinada'}",
            f"Causa: {', '.join(causes) or 'no determinada'}",
            f"Déficit máximo: {maximum:.2f} °C" if maximum is not None else "Déficit máximo: no disponible",
            f"Fin del horizonte conservado: {remaining}",
            "",
            "No se activa el candidato degradado; se conserva el último plan "
            "VALID o CONVERGING mientras tenga slots vigentes. Si no queda "
            "un sustituto activable al agotarse ese horizonte, las salidas se "
            "mantendrán apagadas.",
        )
    )
    return subject, body


def alert_catalogue(enabled: Mapping[str, bool] | None = None) -> list[dict[str, Any]]:
    """The catalogue as the API exposes it, with its activation state."""
    state = enabled or {}
    return [
        {
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "enabled": bool(state.get(item.name, True)),
        }
        for item in ALERT_TYPES
    ]


__all__ = [
    "ALERT_TYPES",
    "ALERT_TYPES_BY_NAME",
    "MAX_ATTEMPTS",
    "PLAN_RECALCULATION_DEGRADED",
    "PLAN_RECALCULATION_INVALID",
    "AlertDeliveryError",
    "AlertRepository",
    "AlertSender",
    "AlertService",
    "AlertType",
    "PendingAlert",
    "SmtpAlertSender",
    "alert_catalogue",
    "build_alert_service",
    "plan_recalculation_invalid_message",
    "plan_recalculation_degraded_message",
]
