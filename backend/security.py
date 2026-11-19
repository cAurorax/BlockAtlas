"""Salted password hashing and opaque, revocable sessions."""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def expires():
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(
        timespec="seconds"
    )


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 260000
    ).hex()
    return f"pbkdf2_sha256$260000${salt}${digest}"


def verify_password(password, encoded):
    _, iterations, salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    ).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def can_view_post(post, user, is_friend):
    """Six independent control-flow paths, tested in tests/test_policy.py."""
    if user["role"] == "admin":
        return True
    if post["user_id"] == user["id"]:
        return True
    if post["hidden"]:
        return False
    if post["visibility"] == "public":
        return True
    if post["visibility"] == "friends":
        return is_friend
    return False
