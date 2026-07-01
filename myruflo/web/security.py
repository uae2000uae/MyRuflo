"""Password hashing — stdlib-only (hashlib.pbkdf2_hmac), no bcrypt/passlib
dependency, consistent with the rest of MyRuflo's dependency-light approach.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_str, salt, hash_hex = encoded.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations_str))
    return hmac.compare_digest(digest.hex(), hash_hex)
