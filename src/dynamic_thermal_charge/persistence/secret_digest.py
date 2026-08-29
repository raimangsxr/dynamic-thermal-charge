"""One-way credential digests shared by bootstrap and fallback stores."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


ALGORITHM = "scrypt"


def digest_secret(secret: str, *, salt: bytes | None = None) -> str:
    if not secret:
        raise ValueError("a secret cannot be empty")
    actual_salt = os.urandom(16) if salt is None else salt
    digest = hashlib.scrypt(
        secret.encode("utf-8"), salt=actual_salt, n=2**14, r=8, p=1, dklen=32
    )
    return ":".join(
        (
            ALGORITHM,
            base64.urlsafe_b64encode(actual_salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def secret_matches(secret: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, expected_text = encoded.split(":", 2)
        if algorithm != ALGORITHM:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
    except (ValueError, UnicodeError):
        return False
    actual = hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=len(expected)
    )
    return hmac.compare_digest(actual, expected)


__all__ = ["digest_secret", "secret_matches"]
