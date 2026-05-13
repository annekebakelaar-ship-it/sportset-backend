"""
AES-256-GCM token encryption.
Key: TOKEN_ENCRYPTION_KEY env var — 32 bytes as 64 hex chars.
Format: base64(12-byte IV || ciphertext || 16-byte GCM tag)
"""
import os
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key() -> bytes:
    hex_key = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if len(hex_key) != 64:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes). "
            "Generate with: openssl rand -hex 32"
        )
    return bytes.fromhex(hex_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Every call generates a fresh 12-byte IV."""
    aesgcm = AESGCM(_key())
    iv = os.urandom(12)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ciphertext_with_tag).decode("ascii")


def decrypt(payload: str) -> str:
    """Decrypt a payload produced by encrypt(). Raises on tamper or wrong key."""
    raw = base64.b64decode(payload)
    iv, ciphertext_with_tag = raw[:12], raw[12:]
    aesgcm = AESGCM(_key())
    return aesgcm.decrypt(iv, ciphertext_with_tag, None).decode("utf-8")
