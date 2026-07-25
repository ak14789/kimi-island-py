"""Token acquisition: Kimi CLI credentials (preferred) + manual browser token."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

KIMI_DIR = Path.home() / ".kimi"
CLI_CREDENTIALS_FILE = KIMI_DIR / "credentials" / "kimi-code.json"
DEVICE_ID_FILE = KIMI_DIR / "device_id"


def parse_jwt_claims(token: str) -> dict:
    """Decode the payload of a JWT without verifying the signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload = parts[1].replace("-", "+").replace("_", "/")
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.b64decode(payload)
        return json.loads(decoded)
    except Exception as exc:  # noqa: BLE001 - normalize all decode failures
        raise ValueError(f"JWT payload decode failed: {exc}") from exc


def jwt_expiry(token: str) -> Optional[float]:
    try:
        exp = parse_jwt_claims(token).get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, TypeError):
        return None


def is_expired(expires_at: Optional[float], buffer_seconds: int = 0) -> bool:
    """Unknown expiry is treated as not expired (let the server decide)."""
    if expires_at is None:
        return False
    return time.time() + buffer_seconds >= expires_at


@dataclass
class TokenInfo:
    token: str
    source: str  # "cli" | "manual"
    expires_at: Optional[float]

    @property
    def expired(self) -> bool:
        return is_expired(self.expires_at)

    def claims(self) -> dict:
        return parse_jwt_claims(self.token)


def load_cli_token() -> Optional[TokenInfo]:
    """Read the Kimi Code CLI OAuth credential, if present."""
    try:
        data = json.loads(CLI_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = data.get("access_token")
    if not token:
        return None
    expires_at = data.get("expires_at")
    try:
        expires_at = float(expires_at) if expires_at is not None else jwt_expiry(token)
    except (TypeError, ValueError):
        expires_at = jwt_expiry(token)
    return TokenInfo(token=token, source="cli", expires_at=expires_at)


def load_manual_token(config: dict) -> Optional[TokenInfo]:
    token = (config.get("kimi_token") or "").strip()
    if not token:
        return None
    return TokenInfo(token=token, source="manual", expires_at=jwt_expiry(token))


def resolve_token(config: dict) -> Optional[TokenInfo]:
    """Prefer the CLI credential; fall back to the manually pasted browser token.

    If the CLI token is expired but a manual token exists, the manual one wins.
    """
    cli = load_cli_token()
    manual = load_manual_token(config)
    if cli is not None and not cli.expired:
        return cli
    if manual is not None and not manual.expired:
        return manual
    # Return whatever exists so the caller can report an accurate expiry error.
    return cli or manual


def get_device_id() -> str:
    try:
        value = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    return "unknown_device"
