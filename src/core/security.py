"""
Security utilities: password hashing, JWT, token encryption (AES-256-GCM)
"""

import json
import logging
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from passlib.context import CryptContext

from src.core.config import settings

logger = logging.getLogger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================================
# Password Hashing
# ============================================================================


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    return pwd_context.verify(plain, hashed)


# ============================================================================
# AES-256-GCM Token Encryption (for Oura + Mollie tokens)
# ============================================================================


def _get_encryption_key() -> bytes:
    """Parse hex-encoded encryption key from config. Must be 32 bytes (256 bits)."""
    if not settings.token_encryption_key:
        raise ValueError("TOKEN_ENCRYPTION_KEY not configured")
    try:
        key_bytes = bytes.fromhex(settings.token_encryption_key)
        if len(key_bytes) != 32:
            raise ValueError(f"TOKEN_ENCRYPTION_KEY must be 32 bytes, got {len(key_bytes)}")
        return key_bytes
    except ValueError as e:
        raise ValueError(f"Invalid TOKEN_ENCRYPTION_KEY format: {e}") from e


def encrypt_token(token_data: dict) -> str:
    """
    Encrypt token data (e.g., Oura OAuth tokens) using AES-256-GCM.
    
    Args:
        token_data: Dictionary with access_token, refresh_token, expires_at, etc.
    
    Returns:
        Base64-encoded string: "nonce:ciphertext:tag"
    """
    key = _get_encryption_key()
    
    # Serialize token data to JSON
    plaintext = json.dumps(token_data).encode("utf-8")
    
    # Generate 96-bit nonce (12 bytes) — standard for GCM
    nonce = AESGCM.generate_nonce(12)
    
    # Encrypt with GCM (authentication tag is automatically included)
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(nonce, plaintext, None)
    
    # Return base64: nonce:ciphertext (GCM tag is appended by cryptography lib)
    nonce_b64 = b64encode(nonce).decode("utf-8")
    ciphertext_b64 = b64encode(ciphertext).decode("utf-8")
    
    return f"{nonce_b64}:{ciphertext_b64}"


def decrypt_token(encrypted_data: str) -> dict:
    """
    Decrypt AES-256-GCM encrypted token.
    
    Args:
        encrypted_data: Base64-encoded "nonce:ciphertext:tag" string
    
    Returns:
        Dictionary with decrypted token data
    """
    key = _get_encryption_key()
    
    try:
        nonce_b64, ciphertext_b64 = encrypted_data.split(":")
        nonce = b64decode(nonce_b64)
        ciphertext = b64decode(ciphertext_b64)
        
        # Decrypt with GCM (verification is automatic)
        cipher = AESGCM(key)
        plaintext = cipher.decrypt(nonce, ciphertext, None)
        
        return json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        logger.error(f"Token decryption failed: {e}")
        raise ValueError(f"Invalid or corrupted encrypted token: {e}") from e


# ============================================================================
# JWT Token Generation (for user sessions)
# ============================================================================


def create_access_token(user_id: str, email: str, expires_delta: timedelta | None = None) -> str:
    """
    Create JWT access token for user session.
    
    Args:
        user_id: User UUID
        email: User email
        expires_delta: Token expiry (default: 7 days)
    
    Returns:
        Signed JWT token string
    """
    from jose import jwt
    
    if expires_delta is None:
        expires_delta = timedelta(days=7)
    
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
    }
    
    token = jwt.encode(payload, settings.app_secret_key, algorithm="HS256")
    return token


def verify_access_token(token: str) -> dict:
    """
    Verify and decode JWT access token.
    
    Returns:
        Decoded payload dict with 'sub' (user_id) and 'email'
    """
    from jose import jwt, JWTError
    
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id or not email:
            raise ValueError("Missing required claims in JWT")
        return {"user_id": user_id, "email": email}
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e
