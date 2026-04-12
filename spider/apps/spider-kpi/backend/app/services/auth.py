from __future__ import annotations

import hashlib
import hmac
import os
from typing import Iterable


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000


def normalize_email(email: str) -> str:
    return email.strip().lower()


def extract_email_domain(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[-1]


def email_domain_allowed(email: str, allowed_domains: Iterable[str]) -> bool:
    domain = extract_email_domain(email)
    normalized_domains = {str(item).strip().lower() for item in allowed_domains if str(item).strip()}
    return bool(domain) and domain in normalized_domains


def validate_password_strength(password: str) -> str | None:
    if len(password) < 12:
        return "Password must be at least 12 characters long"
    if password.strip() != password:
        return "Password cannot start or end with spaces"
    return None


def hash_password(password: str, *, salt: str | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    actual_salt = salt or os.urandom(16).hex()
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"{PASSWORD_SCHEME}${iterations}${actual_salt}${derived}"


def verify_password(password: str, encoded_password: str | None) -> bool:
    if not encoded_password:
        return False
    try:
        scheme, iterations_raw, salt, expected_hash = encoded_password.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
    except ValueError:
        return False
    candidate = hash_password(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(candidate, encoded_password)
