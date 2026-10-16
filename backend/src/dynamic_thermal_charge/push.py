"""Best-effort Web Push delivery for terminal calibration notifications.

The persistence queue is authoritative.  This module deliberately treats the
optional ``pywebpush`` adapter as a transport detail, so an unavailable Push
library or VAPID secret can only change the channel status and never calibration
or relay control.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4


logger = logging.getLogger(__name__)


class PushDeliveryError(RuntimeError):
    pass


class PushUnsupported(PushDeliveryError):
    pass


class PushExpired(PushDeliveryError):
    pass


class WebPushDelivery:
    def __init__(self, repository, *, sender: Callable | None = None, clock=None) -> None:
        self._repository = repository
        self._sender = sender or _default_sender
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owner = f"push-{os.getpid()}-{uuid4().hex[:12]}"

    def deliver_pending(
        self,
        *,
        session_id: str | None = None,
        alert_id: int | None = None,
    ) -> int:
        """Deliver pending/error attempts once; return successful deliveries."""
        if alert_id is not None and hasattr(self._repository, "push_attempts_for_alert"):
            attempts = self._repository.push_attempts_for_alert(alert_id)
        else:
            attempts = self._repository.push_attempts(session_id) if session_id else ()
        delivered = 0
        handoff = getattr(self._repository, "deliver_claimed_push", None)
        for attempt in attempts:
            if attempt.status not in {"pending", "error"}:
                continue
            claimer = getattr(self._repository, "claim_push_attempt", None)
            if callable(claimer) and not claimer(
                attempt.id,
                owner=self._owner,
                at=self._clock(),
            ):
                continue
            subscription = self._repository.subscription(attempt.subscription_id)
            if subscription is None or subscription.status != "active":
                _mark_push_attempt(
                    self._repository,
                    attempt.id,
                    status="expired",
                    error="subscription_not_active",
                    at=self._clock(),
                    owner=self._owner,
                )
                continue
            notification_id = alert_id if alert_id is not None else attempt.alert_id
            notification = (
                self._repository.alert_notification(notification_id)
                if notification_id is not None
                and hasattr(self._repository, "alert_notification")
                else None
            )
            payload_data = {
                "type": (
                    "operator_alert"
                    if notification is not None
                    else "thermal_calibration"
                ),
                "alert_id": attempt.alert_id,
                "session_id": attempt.session_id,
            }
            if notification is not None:
                payload_data.update(
                    {
                        "alert_type": notification.alert_type,
                        "severity": notification.severity,
                        "title": notification.title,
                        "body": notification.body,
                    }
                )
            payload = json.dumps(
                payload_data,
                sort_keys=True,
                separators=(",", ":"),
            )
            try:
                if callable(handoff):
                    outcome = handoff(
                        attempt.id,
                        owner=self._owner,
                        at=self._clock(),
                        alert_type=(
                            notification.alert_type if notification is not None else None
                        ),
                        send=lambda active_subscription: self._sender(
                            active_subscription, payload
                        ),
                    )
                    if outcome == "inactive":
                        _mark_push_attempt(
                            self._repository,
                            attempt.id,
                            status="expired",
                            error="subscription_not_active",
                            at=self._clock(),
                            owner=self._owner,
                        )
                    if outcome != "sent":
                        continue
                else:
                    type_enabled = getattr(self._repository, "alert_type_enabled", None)
                    if notification is not None and callable(type_enabled):
                        try:
                            enabled = bool(type_enabled(notification.alert_type))
                        except Exception:  # noqa: BLE001 - catalogue reads are best effort
                            logger.warning(
                                "Could not read catalogue state for Push alert %s",
                                notification.alert_type,
                                exc_info=True,
                            )
                            enabled = True
                        if not enabled:
                            _mark_push_attempt(
                                self._repository,
                                attempt.id,
                                status="denied",
                                error="alert_type_disabled",
                                at=self._clock(),
                                owner=self._owner,
                            )
                            continue
                    self._sender(subscription, payload)
            except PushUnsupported as exc:
                _mark_push_attempt(
                    self._repository,
                    attempt.id,
                    status="unsupported",
                    error=str(exc),
                    at=self._clock(),
                    owner=self._owner,
                )
                continue
            except PushExpired as exc:
                marked = _mark_push_attempt(
                    self._repository,
                    attempt.id,
                    status="expired",
                    error=str(exc),
                    at=self._clock(),
                    owner=self._owner,
                )
                if marked is False:
                    continue
                self._repository.mark_subscription_status(
                    subscription.id, status="expired", error=str(exc), at=self._clock()
                )
                continue
            except PermissionError as exc:
                _mark_push_attempt(
                    self._repository,
                    attempt.id,
                    status="denied",
                    error=str(exc),
                    at=self._clock(),
                    owner=self._owner,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - channel failure is isolated
                _mark_push_attempt(
                    self._repository,
                    attempt.id,
                    status="error",
                    error=str(exc),
                    at=self._clock(),
                    owner=self._owner,
                )
                logger.warning("Web Push delivery failed: %s", exc)
                continue
            marked = _mark_push_attempt(
                self._repository,
                attempt.id,
                status="sent",
                at=self._clock(),
                owner=self._owner,
            )
            if marked is False:
                continue
            delivered += 1
        return delivered


def _default_sender(subscription, payload: str) -> None:
    private_key = os.environ.get("DTC_VAPID_PRIVATE_KEY")
    subject = os.environ.get("DTC_VAPID_SUBJECT", "mailto:operator@localhost")
    if not private_key:
        raise PushUnsupported("vapid_private_key_unconfigured")
    try:
        from pywebpush import webpush
    except ImportError as exc:
        raise PushUnsupported("web_push_library_unavailable") from exc
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={"sub": subject},
        )
    except Exception as exc:  # translate provider response without coupling to it
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status in {404, 410}:
            raise PushExpired(f"endpoint_expired_{status}") from exc
        if status in {401, 403}:
            raise PermissionError(f"provider_denied_{status}") from exc
        raise PushDeliveryError(str(exc)) from exc


def _mark_push_attempt(
    repository,
    attempt_id: int,
    *,
    status: str,
    error: str | None = None,
    at: datetime,
    owner: str,
) -> bool | None:
    """Finish a Push attempt while supporting calibration-era fakes."""
    try:
        return repository.mark_push_attempt(
            attempt_id,
            status=status,
            error=error,
            at=at,
            owner=owner,
        )
    except TypeError:
        return repository.mark_push_attempt(
            attempt_id,
            status=status,
            error=error,
            at=at,
        )


__all__ = [
    "PushDeliveryError",
    "PushExpired",
    "PushUnsupported",
    "WebPushDelivery",
]
