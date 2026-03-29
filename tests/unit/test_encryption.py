"""Unit tests for utils.encryption — Fernet-based at-rest encryption."""

import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key() -> str:
    """Generate a fresh Fernet key string for tests."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# encrypt_value / decrypt_value round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip():
    """A value encrypted then decrypted returns the original plaintext."""
    from utils.encryption import decrypt_value, encrypt_value

    key = _make_key()
    plaintext = "el_abc123secretkey"

    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key}):
        token = encrypt_value(plaintext)
        assert token != plaintext
        assert decrypt_value(token) == plaintext


def test_encrypt_produces_fernet_prefix():
    """Encrypted values start with the Fernet token prefix 'gAAAAA'."""
    from utils.encryption import encrypt_value

    key = _make_key()
    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key}):
        token = encrypt_value("el_test")
        assert token.startswith("gAAAAA")


def test_is_encrypted_true_for_fernet_tokens():
    """is_encrypted returns True for Fernet-encrypted tokens."""
    from utils.encryption import encrypt_value, is_encrypted

    key = _make_key()
    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key}):
        token = encrypt_value("el_something")
        assert is_encrypted(token) is True


def test_is_encrypted_false_for_plaintext():
    """is_encrypted returns False for legacy plaintext API keys."""
    from utils.encryption import is_encrypted

    assert is_encrypted("el_abc123") is False
    assert is_encrypted("some-other-value") is False


def test_missing_key_raises_runtime_error():
    """encrypt_value raises RuntimeError when KEY_ENCRYPTION_KEY is not set."""
    from utils.encryption import encrypt_value

    with patch.dict(os.environ, {}, clear=True):
        # Remove the key from environment
        env = {k: v for k, v in os.environ.items() if k != "KEY_ENCRYPTION_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="KEY_ENCRYPTION_KEY"):
                encrypt_value("el_test")


def test_decrypt_legacy_plaintext_returned_as_is(caplog):
    """decrypt_value returns legacy plaintext values unchanged and logs a warning."""
    import logging

    from utils.encryption import decrypt_value

    key = _make_key()
    plaintext = "el_legacykey123"
    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key}):
        with caplog.at_level(logging.WARNING, logger="utils.encryption"):
            result = decrypt_value(plaintext)

    assert result == plaintext
    assert "unencrypted" in caplog.text.lower() or "legacy" in caplog.text.lower()


def test_tampered_token_raises():
    """decrypt_value raises InvalidToken if the ciphertext has been tampered."""
    from cryptography.fernet import InvalidToken

    from utils.encryption import decrypt_value, encrypt_value

    key = _make_key()
    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key}):
        token = encrypt_value("el_original")
        # Flip last character to corrupt the HMAC
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(InvalidToken):
            decrypt_value(tampered)


# ---------------------------------------------------------------------------
# Different keys cannot decrypt each other's tokens
# ---------------------------------------------------------------------------


def test_wrong_key_cannot_decrypt():
    """A token encrypted with key A cannot be decrypted with key B."""
    from cryptography.fernet import InvalidToken

    from utils.encryption import decrypt_value, encrypt_value

    key_a = _make_key()
    key_b = _make_key()

    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key_a}):
        token = encrypt_value("el_secret")

    with patch.dict(os.environ, {"KEY_ENCRYPTION_KEY": key_b}):
        with pytest.raises(InvalidToken):
            decrypt_value(token)
