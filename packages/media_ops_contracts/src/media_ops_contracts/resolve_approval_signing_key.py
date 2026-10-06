"""The HMAC key every signer and verifier in one process shares (write_safe_tools.md §3)."""

import secrets
from functools import cache


def resolve_approval_signing_key(configured: str) -> bytes:
    """APPROVAL_SIGNING_KEY when set; otherwise one random key per process.

    The hub signs and the domain packs verify in the same process, so an unset key must
    still be the same key for both, never a fresh random value per caller.
    """
    return configured.encode() if configured else _process_key()


@cache
def _process_key() -> bytes:
    return secrets.token_bytes(32)
