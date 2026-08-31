"""Token acquisition + OAuth refresh: CLI credentials (preferred) + manual token."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

KIMI_DIR = Path.home() / ".kimi"
CLI_CREDENTIALS_FILE = KIMI_DIR / "credentials" / "kimi-code.json"
DEVICE_ID_FILE = KIMI_DIR / "device_id"

OAUTH_TOKEN_URL = "https://auth.kimi.com/api/oauth/token"
# Public client_id of the open-source kimi-cli OAuth app (not a secret).
KIMI_CODE_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
MIN_REFRESH_THRESHOLD_SECONDS = 300.0  # always refresh at least 5 min early
REFRESH_THRESHOLD_RATIO = 0.5  # or at half lifetime, whichever is larger
UNAUTHORIZED_COOLDOWN_SECONDS = 300.0  # pause auto-refresh after a rejected rt
_refresh_cooldown_until = 0.0  # module-level: skip refresh attempts while cooling


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
    source: str  # "cli" | "manual" | "refresh"
    expires_at: Optional[float]
    refresh_token: Optional[str] = None  # OAuth refresh_token (for auto-renewal)
    refreshed: bool = False  # True when produced by an automatic refresh

    @property
    def expired(self) -> bool:
        return is_expired(self.expires_at)

    def claims(self) -> dict:
        return parse_jwt_claims(self.token)


class TokenRefreshError(Exception):
    """Raised when refreshing the access token fails.

    kind is one of: "unauthorized" (refresh_token rejected -> re-login
    required), "network", "http", "parse".
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _engage_unauthorized_cooldown() -> None:
    """Pause auto-refresh attempts after a rejected refresh_token.

    Keeps the poller from hammering the OAuth endpoint every cycle when the
    refresh_token is dead and only a manual re-login can recover.
    """
    global _refresh_cooldown_until
    _refresh_cooldown_until = time.time() + UNAUTHORIZED_COOLDOWN_SECONDS


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
    return TokenInfo(
        token=token,
        source="cli",
        expires_at=expires_at,
        refresh_token=data.get("refresh_token"),
    )


def load_manual_token(config: dict) -> Optional[TokenInfo]:
    token = (config.get("kimi_token") or "").strip()
    if not token:
        return None
    refresh = (config.get("kimi_refresh_token") or "").strip() or None
    return TokenInfo(
        token=token, source="manual", expires_at=jwt_expiry(token), refresh_token=refresh
    )


def refresh_access_token(refresh_token: str) -> TokenInfo:
    """Exchange a refresh_token for a fresh access token (RFC 6749 section 6).

    Mirrors the kimi-cli implementation: POST the refresh_token grant to the
    OAuth token endpoint and build a TokenInfo whose expires_at comes from
    expires_in. Raises TokenRefreshError with a `kind` describing the failure.
    """
    try:
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": KIMI_CODE_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise TokenRefreshError("network", f"自动刷新请求失败: {exc}") from exc
    if resp.status_code in (401, 403):
        # A rejected refresh_token will not recover on its own.
        raise TokenRefreshError(
            "unauthorized", "refresh_token 已失效，请重新登录获取新凭证"
        )
    if not resp.ok:
        # Per RFC 6749 the server reports a dead grant as 400 invalid_grant
        # (verified live), so treat those as unauthorized, not transient.
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        error = payload.get("error") or ""
        if resp.status_code == 400 and error in (
            "invalid_grant",
            "invalid_client",
            "unauthorized_client",
        ):
            raise TokenRefreshError(
                "unauthorized", "refresh_token 已失效，请重新登录获取新凭证"
            )
        raise TokenRefreshError("http", f"自动刷新失败: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise TokenRefreshError("parse", f"自动刷新响应解析失败: {exc}") from exc
    access = payload.get("access_token")
    if not access:
        raise TokenRefreshError("parse", "自动刷新响应缺少 access_token")
    try:
        expires_in = float(payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0.0
    if expires_in <= 0:
        expires_in = float(jwt_expiry(access) or 0) - time.time()
    if expires_in <= 0:
        expires_in = 3600.0  # defensive default when the lifetime is unknown
    new_refresh = payload.get("refresh_token") or refresh_token  # rotation-aware
    return TokenInfo(
        token=access,
        source="refresh",
        expires_at=time.time() + expires_in,
        refresh_token=new_refresh,
        refreshed=True,
    )


def _refresh_threshold(token: TokenInfo) -> int:
    """Seconds before expiry at which the token should be refreshed.

    Half the token lifetime (from the JWT iat claim) or 5 minutes, whichever
    is larger — same policy as kimi-cli.
    """
    lifetime: Optional[float] = None
    try:
        iat = token.claims().get("iat")
        if iat is not None and token.expires_at is not None:
            lifetime = float(token.expires_at) - float(iat)
    except (ValueError, TypeError):
        lifetime = None
    if lifetime is not None and lifetime > 0:
        return int(max(MIN_REFRESH_THRESHOLD_SECONDS, lifetime * REFRESH_THRESHOLD_RATIO))
    return int(MIN_REFRESH_THRESHOLD_SECONDS)


def store_refreshed_token(config: dict, refreshed: TokenInfo) -> None:
    """Persist a refreshed token into the config dict (never the CLI file).

    The CLI credential file stays read-only to avoid interfering with the
    kimi-cli's own token rotation; the fresh pair lives in config.json instead.
    """
    config["kimi_token"] = refreshed.token
    if refreshed.refresh_token:
        config["kimi_refresh_token"] = refreshed.refresh_token


def resolve_token(config: dict, auto_refresh: bool = False) -> Optional[TokenInfo]:
    """Prefer the CLI credential; fall back to the manually pasted browser token.

    If the CLI token is expired but a manual token exists, the manual one wins.
    With auto_refresh=True, a chosen token that is expired (or within the
    refresh threshold) is renewed via its refresh_token; on success the fresh
    pair is stored back into `config` and returned with refreshed=True.
    """
    cli = load_cli_token()
    manual = load_manual_token(config)
    if cli is not None and not cli.expired:
        chosen = cli
    elif manual is not None and not manual.expired:
        chosen = manual
    else:
        chosen = cli or manual

    if (
        auto_refresh
        and chosen is not None
        and chosen.refresh_token
        and time.time() >= _refresh_cooldown_until
        and is_expired(chosen.expires_at, buffer_seconds=_refresh_threshold(chosen))
    ):
        try:
            refreshed = refresh_access_token(chosen.refresh_token)
        except TokenRefreshError as exc:
            if exc.kind == "unauthorized":
                # Dead refresh_token: cool down instead of retrying every cycle.
                _engage_unauthorized_cooldown()
            # Keep serving the current token; the 401 retry in api.py will
            # surface a precise error if it is truly dead.
            refreshed = None
        if refreshed is not None:
            store_refreshed_token(config, refreshed)
            return refreshed

    # Return whatever exists so the caller can report an accurate expiry error.
    return chosen


def get_device_id() -> str:
    try:
        value = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    return "unknown_device"
