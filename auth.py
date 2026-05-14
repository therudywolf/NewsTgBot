"""Authentication helpers for the NewsTgBot admin panel."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

import config
from database import Database

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 480_000


def hash_password(password: str) -> str:
    """Hash *password* using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verify *password* against a stored PBKDF2 hash."""
    try:
        scheme, iterations_str, salt_b64, digest_b64 = password_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except (TypeError, ValueError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def is_admin_configured(db: Optional[Database] = None) -> bool:
    """Return True when the admin account is configured."""
    database = db or Database()
    return bool(database.get_setting("admin_password_hash") or config.get_admin_password_hash())


def ensure_session_secret(db: Optional[Database] = None) -> str:
    """Ensure a persistent session secret exists and return it."""
    database = db or Database()
    secret = database.get_setting("admin_session_secret") or config.get_admin_session_secret()
    if secret:
        return str(secret)

    secret = secrets.token_urlsafe(48)
    database.set_setting("admin_session_secret", secret)
    return secret
