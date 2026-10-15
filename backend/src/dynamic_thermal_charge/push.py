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

    def deliver_pending(self, *, session_id: str | None = None) -> int:
        """Deliver pending/error attempts once; return successful deliveries."""
        attempts = self._repository.push_attempts(session_id) if session_id else ()
        delivered = 0
        for attempt in attempts:
            if attempt.status not in {"pending", "error"}:
                continue
            subscription = self._repository.subscription(attempt.subscription_id)
            if subscription is None or subscription.status != "active":
                self._repository.mark_push_attempt(
                    attempt.id, status="expired", error="subscription_not_active", at=self._clock()
                )
                continue
            payload = json.dumps(
                {
                    "type": "thermal_calibration",
                    "session_id": attempt.session_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            try:
                self._sender(subscription, payload)
            except PushUnsupported as exc:
                self._repository.mark_push_attempt(
                    attempt.id, status="unsupported", error=str(exc), at=self._clock()
                )
                continue
            except PushExpired as exc:
                self._repository.mark_push_attempt(
                    attempt.id, status="expired", error=str(exc), at=self._clock()
                )
                self._repository.mark_subscription_status(
                    subscription.id, status="expired", error=str(exc), at=self._clock()
                )
                continue
            except PermissionError as exc:
                self._repository.mark_push_attempt(
                    attempt.id, status="denied", error=str(exc), at=self._clock()
                )
                continue
            except Exception as exc:  # noqa: BLE001 - channel failure is isolated
                self._repository.mark_push_attempt(
                    attempt.id, status="error", error=str(exc), at=self._clock()
                )
                logger.warning("Web Push delivery failed: %s", exc)
                continue
            self._repository.mark_push_attempt(attempt.id, status="sent", at=self._clock())
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


__all__ = [
    "PushDeliveryError",
    "PushExpired",
    "PushUnsupported",
    "WebPushDelivery",
]
