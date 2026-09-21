"""Small adapter for secrets that must not be persisted in settings.json."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SERVICE_NAME = "VoicerStudio"
HF_TOKEN_ACCOUNT = "huggingface_token"


def get_huggingface_token() -> str:
    """Return the Hugging Face token from the operating-system credential store."""
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, HF_TOKEN_ACCOUNT) or ""
    except Exception as exc:
        log.debug("Credential store is unavailable: %s", exc)
        return ""


def set_huggingface_token(token: str) -> bool:
    """Save or clear the token. Returns False rather than falling back to plaintext."""
    token = token.strip()
    try:
        import keyring
        if token:
            keyring.set_password(SERVICE_NAME, HF_TOKEN_ACCOUNT, token)
        else:
            try:
                keyring.delete_password(SERVICE_NAME, HF_TOKEN_ACCOUNT)
            except keyring.errors.PasswordDeleteError:
                pass
        return True
    except Exception as exc:
        # A missing optional credential backend must not prevent users without a
        # token from saving unrelated preferences.
        if not token:
            return True
        log.warning("Could not access the operating-system credential store: %s", exc)
        return False
