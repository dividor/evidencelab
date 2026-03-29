"""Symmetric encryption for sensitive values stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` library
so that values like API keys are encrypted at rest.  A stolen database
snapshot is therefore useless without the separate encryption key.

Configuration
-------------
Set ``KEY_ENCRYPTION_KEY`` in the environment to a URL-safe base64-encoded
32-byte key.  Generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If ``KEY_ENCRYPTION_KEY`` is not set, :func:`encrypt_value` raises
``RuntimeError`` at runtime so the misconfiguration surfaces immediately.

Migration path for existing plaintext values
--------------------------------------------
Fernet tokens always start with ``gAAAAA``.  Values that do *not* start
with this prefix are treated as legacy plaintext and returned as-is by
:func:`decrypt_value` (they should be replaced by regenerating new keys).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Fernet token prefix in URL-safe base64 — used to detect encrypted vs legacy
_FERNET_PREFIX = "gAAAAA"


def _get_fernet():  # type: ignore[return]
    """Return a Fernet instance using KEY_ENCRYPTION_KEY from the environment.

    Raises RuntimeError if the key is missing or invalid.
    """
    from cryptography.fernet import Fernet  # lazy import — optional dependency

    key = os.environ.get("KEY_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "KEY_ENCRYPTION_KEY is not set. "
            "Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 Fernet token.

    Raises ``RuntimeError`` if ``KEY_ENCRYPTION_KEY`` is not configured.
    """
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted value.

    If *ciphertext* does not look like a Fernet token (legacy plaintext from
    before encryption was introduced), it is returned unchanged and a warning
    is logged — the admin should regenerate that key.

    Raises ``cryptography.fernet.InvalidToken`` if the value is a Fernet
    token but has been tampered with.
    Raises ``RuntimeError`` if ``KEY_ENCRYPTION_KEY`` is not configured.
    """
    if not ciphertext.startswith(_FERNET_PREFIX):
        logger.warning(
            "API key value appears to be unencrypted plaintext (legacy). "
            "Regenerate this key to store it encrypted."
        )
        return ciphertext
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def is_encrypted(value: str) -> bool:
    """Return True if *value* looks like a Fernet-encrypted token."""
    return value.startswith(_FERNET_PREFIX)
