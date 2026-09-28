"""
Security & Cryptography Engine.
Implements:
1. PBKDF2-HMAC-SHA256 password hashing & verification.
2. Symmetric authenticated encryption (Fernet/AES-128-CBC+HMAC) for OAuth credentials at rest.
3. JWT token generation, signature verification, and claims validation.
4. Robust SSRF protection (DNS validation, private subnets, cloud metadata blocking).
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

logger = logging.getLogger("leadflow.security")

# ── Password Hashing (PBKDF2-HMAC-SHA256) ────────────────────────────────────

PBKDF2_ITERATIONS = 310_000  # OWASP recommendation
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = os.urandom(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    # Format: pbkdf2_sha256$iterations$salt_b64$hash_b64
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(derived).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its PBKDF2 hash using constant-time comparison."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2].encode("ascii"))
        expected_hash = base64.b64decode(parts[3].encode("ascii"))
        test_hash = hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(expected_hash, test_hash)
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False


# ── Credential Encryption at Rest (Fernet) ───────────────────────────────────

def _get_fernet() -> Fernet:
    """Initialize Fernet cipher using configured ENCRYPTION_KEY."""
    key = settings.ENCRYPTION_KEY.encode("utf-8")
    # Ensure key is valid 32-byte urlsafe base64
    try:
        return Fernet(key)
    except Exception:
        # If key is raw 32 bytes or needs normalization, pad/encode safely
        raw = hashlib.sha256(key).digest()
        return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a sensitive string (e.g. OAuth token JSON) for database storage."""
    if not plaintext:
        return ""
    cipher = _get_fernet()
    encrypted_bytes = cipher.encrypt(plaintext.encode("utf-8"))
    return encrypted_bytes.decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt an encrypted secret string from database storage."""
    if not ciphertext:
        return ""
    cipher = _get_fernet()
    try:
        decrypted_bytes = cipher.decrypt(ciphertext.encode("ascii"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt secret: invalid token or wrong encryption key")
        raise ValueError("Decryption failed: corrupted token or incorrect key")


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """Return a masked representation of a secret for logs/UI."""
    if not secret:
        return "None"
    if len(secret) <= visible_chars * 2:
        return "***"
    return f"{secret[:visible_chars]}...{secret[-visible_chars:]}"


# ── JWT / Session Tokens (HMAC-SHA256) ────────────────────────────────────────

def create_access_token(
    user_id: int,
    organization_id: int,
    role: str = "member",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed HMAC-SHA256 JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user_id),
        "org": organization_id,
        "role": role,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).rstrip(b"=").decode("ascii")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and verify a signed JWT access token. Raises ValueError on failure."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header_b64, payload_b64, sig_b64 = parts
    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(settings.SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    # Handle base64 padding
    rem = len(sig_b64) % 4
    sig_padded = sig_b64 + ("=" * (4 - rem) if rem else "")
    actual_sig = base64.urlsafe_b64decode(sig_padded.encode("ascii"))
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")
    # Decode payload
    rem_p = len(payload_b64) % 4
    payload_padded = payload_b64 + ("=" * (4 - rem_p) if rem_p else "")
    payload_data = json.loads(base64.urlsafe_b64decode(payload_padded.encode("ascii")).decode("utf-8"))
    # Check expiration
    exp = payload_data.get("exp")
    if exp and datetime.now(timezone.utc).timestamp() > exp:
        raise ValueError("Token has expired")
    return payload_data


# ── SSRF Defense Layer ───────────────────────────────────────────────────────

# Blocked IP networks: RFC 1918, Loopback, Link-Local (Cloud Metadata), Carrier-Grade NAT
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # AWS/GCP metadata 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6 ranges
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_and_sanitize_target_url(url: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validate target URL against SSRF attacks.
    Ensures:
    1. Valid HTTP or HTTPS scheme.
    2. Host is not empty or blacklisted hostname ('localhost', etc.).
    3. Hostname resolves only to public, globally routable IPs (no RFC 1918, loopback, or metadata).
    
    Returns:
        (is_safe, sanitized_url, rejection_reason)
    """
    if not url:
        return False, "", "URL is empty"

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, url, f"Malformed URL syntax: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, url, f"Unsupported scheme: {parsed.scheme} (only http and https allowed)"

    hostname = parsed.hostname
    if not hostname:
        return False, url, "URL missing hostname"

    hostname_lower = hostname.lower()
    if hostname_lower in ("localhost", "local", "internal", "metadata.google.internal"):
        return False, url, f"Target hostname '{hostname}' is reserved/internal"

    # Resolve IP addresses for hostname
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, url, f"DNS resolution failed for '{hostname}': {e}"

    resolved_ips = set()
    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            resolved_ips.add(ip_obj)
        except ValueError:
            return False, url, f"Invalid resolved IP: {ip_str}"

    if not resolved_ips:
        return False, url, f"No IP addresses resolved for '{hostname}'"

    # Check each resolved IP against blocked networks
    for ip in resolved_ips:
        if ip.is_loopback:
            return False, url, f"Resolved IP {ip} is loopback"
        if ip.is_private:
            return False, url, f"Resolved IP {ip} is in a private network (RFC 1918)"
        if ip.is_link_local:
            return False, url, f"Resolved IP {ip} is link-local / cloud metadata"
        if ip.is_multicast:
            return False, url, f"Resolved IP {ip} is multicast"
        if ip.is_reserved:
            return False, url, f"Resolved IP {ip} is reserved"
        for blocked in BLOCKED_NETWORKS:
            if ip in blocked:
                return False, url, f"Resolved IP {ip} is in blocked range {blocked}"

    return True, url, None
