"""
Unit Tests for Security Engine.
Tests:
1. PBKDF2 Password hashing, salt randomness, and verification.
2. Symmetric authenticated encryption (Fernet) of sensitive secrets at rest.
3. JWT creation, signature integrity, and expiration verification.
4. SSRF Defense: blocks private IP ranges, loopback, AWS metadata, and allows public domains.
"""

import time
from datetime import timedelta
import pytest

from core.security import (
    hash_password, verify_password,
    encrypt_secret, decrypt_secret, mask_secret,
    create_access_token, decode_access_token,
    validate_and_sanitize_target_url
)


def test_password_hashing_and_verification():
    raw_pass = "SuperSecretPassword123!"
    hashed = hash_password(raw_pass)

    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False

    # Unique salts should produce different hashes for the same password
    hashed_2 = hash_password(raw_pass)
    assert hashed != hashed_2


def test_secret_encryption_at_rest():
    secret_token = '{"access_token": "ya29.a0AfH6...", "refresh_token": "1//04g..."}'
    encrypted = encrypt_secret(secret_token)

    assert encrypted != secret_token
    assert len(encrypted) > len(secret_token)

    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret_token


def test_mask_secret():
    secret = "AIzaSyD-1234567890abcdef"
    masked = mask_secret(secret, visible_chars=4)
    assert masked == "AIza...cdef"
    assert mask_secret("", 4) == "None"


def test_jwt_lifecycle_and_tampering():
    token = create_access_token(user_id=42, organization_id=7, role="admin")
    payload = decode_access_token(token)

    assert payload["sub"] == "42"
    assert payload["org"] == 7
    assert payload["role"] == "admin"
    assert payload["type"] == "access"

    # Test tampering with token
    parts = token.split(".")
    tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

    with pytest.raises(ValueError, match="Invalid token signature"):
        decode_access_token(tampered_token)


def test_jwt_expiration():
    short_token = create_access_token(
        user_id=1, organization_id=1, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(ValueError, match="Token has expired"):
        decode_access_token(short_token)


@pytest.mark.parametrize("malicious_url,expected_blocked", [
    ("http://127.0.0.1/admin", True),
    ("http://localhost:8000/api", True),
    ("http://169.254.169.254/latest/meta-data/", True),
    ("http://10.0.0.1/internal", True),
    ("http://172.16.0.5/secrets", True),
    ("http://192.168.1.100/router", True),
    ("http://0.0.0.0/debug", True),
    ("ftp://example.com/file", True),
    ("", True),
])
def test_ssrf_protection_blocks_dangerous_targets(malicious_url, expected_blocked):
    is_safe, _, reason = validate_and_sanitize_target_url(malicious_url)
    assert is_safe is False
    assert reason is not None


def test_ssrf_allows_public_domains():
    is_safe, sanitized, reason = validate_and_sanitize_target_url("https://google.com")
    assert is_safe is True
    assert sanitized.startswith("https://")
    assert reason is None
