"""Unit tests for auth + normalization logic (no network, no Qt)."""
from __future__ import annotations

import base64
import json
import time

import pytest

from kimi_island import api, auth, models


def make_jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


# ------------------------------------------------------------------ JWT
def test_parse_jwt_claims_handles_base64url_without_padding():
    token = make_jwt({"sub": "user_1", "ssid": "42"})
    claims = auth.parse_jwt_claims(token)
    assert claims["sub"] == "user_1"
    assert claims["ssid"] == "42"


def test_parse_jwt_claims_rejects_malformed():
    for bad in ("not-a-jwt", "a.b", "a.!!!.c"):
        try:
            auth.parse_jwt_claims(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should reject {bad!r}")


def test_expiry_checks():
    future = time.time() + 3600
    past = time.time() - 10
    assert not auth.is_expired(future)
    assert auth.is_expired(past)
    assert auth.is_expired(future, buffer_seconds=7200)
    assert not auth.is_expired(None)  # unknown expiry -> let server decide


def test_token_preference_cli_first_then_manual(monkeypatch):
    live_cli = auth.TokenInfo(make_jwt({"sub": "u"}), "cli", time.time() + 100)
    manual = auth.TokenInfo(make_jwt({"sub": "u"}), "manual", time.time() + 100)
    monkeypatch.setattr(auth, "load_cli_token", lambda: live_cli)
    monkeypatch.setattr(auth, "load_manual_token", lambda cfg: manual)
    assert auth.resolve_token({}).source == "cli"

    expired_cli = auth.TokenInfo(make_jwt({"sub": "u"}), "cli", time.time() - 100)
    monkeypatch.setattr(auth, "load_cli_token", lambda: expired_cli)
    assert auth.resolve_token({}).source == "manual"

    monkeypatch.setattr(auth, "load_cli_token", lambda: None)
    assert auth.resolve_token({}).source == "manual"
    monkeypatch.setattr(auth, "load_manual_token", lambda cfg: None)
    assert auth.resolve_token({}) is None


# ------------------------------------------------------------ token refresh
@pytest.fixture(autouse=True)
def reset_refresh_cooldown():
    """Keep the module-level refresh cooldown from leaking between tests."""
    auth._refresh_cooldown_until = 0.0
    yield
    auth._refresh_cooldown_until = 0.0


def test_resolve_token_refreshes_near_expiry_and_persists(monkeypatch):
    """Expired token + valid refresh_token -> auto refresh updates the config."""
    fresh = auth.TokenInfo(
        token=make_jwt({"sub": "u", "exp": time.time() + 3600}),
        source="refresh",
        expires_at=time.time() + 3600,
        refresh_token="rt_new",
        refreshed=True,
    )
    seen: list = []

    def fake_refresh(rt: str) -> auth.TokenInfo:
        seen.append(rt)
        return fresh

    monkeypatch.setattr(auth, "refresh_access_token", fake_refresh)
    cfg = {
        "kimi_token": make_jwt({"sub": "u", "exp": time.time() - 100}),
        "kimi_refresh_token": "rt_old",
    }
    tok = auth.resolve_token(cfg, auto_refresh=True)
    assert seen == ["rt_old"]  # refreshed with the stored refresh_token
    assert tok is fresh and tok.refreshed and tok.expires_at > time.time()
    # the fresh pair is written back into the config dict for persistence
    assert cfg["kimi_token"] == fresh.token
    assert cfg["kimi_refresh_token"] == "rt_new"


def test_resolve_token_refresh_rejected_keeps_old_and_cools_down(monkeypatch):
    """Dead refresh_token -> old token returned, no crash, cooldown engaged."""
    def fake_refresh(rt: str) -> auth.TokenInfo:
        raise auth.TokenRefreshError("unauthorized", "refresh_token 已失效")

    monkeypatch.setattr(auth, "refresh_access_token", fake_refresh)
    expired = make_jwt({"sub": "u", "exp": time.time() - 100})
    cfg = {"kimi_token": expired, "kimi_refresh_token": "rt_dead"}
    tok = auth.resolve_token(cfg, auto_refresh=True)
    assert tok is not None and tok.expired and not tok.refreshed
    assert cfg["kimi_token"] == expired  # config untouched on failure
    assert auth._refresh_cooldown_until > time.time()  # backoff engaged


def test_fetch_raw_retries_once_after_refresh(monkeypatch):
    """401 -> refresh via refresh_token -> replay both requests successfully."""
    class FakeResp:
        def __init__(self, status: int, payload: dict):
            self.status_code = status
            self._payload = payload

        @property
        def ok(self) -> bool:
            return self.status_code < 400

        def json(self) -> dict:
            return self._payload

    fresh_jwt = make_jwt({"sub": "u", "ssid": "1", "exp": time.time() + 3600})
    calls: list = []

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        calls.append("refresh" if data is not None else url)
        if data is not None:  # OAuth token endpoint (form-encoded body)
            assert data["grant_type"] == "refresh_token"
            assert data["refresh_token"] == "rt_old"
            return FakeResp(200, {
                "access_token": fresh_jwt,
                "refresh_token": "rt_new",
                "expires_in": 3600,
                "token_type": "Bearer",
            })
        if len([c for c in calls if c != "refresh"]) == 1:
            return FakeResp(401, {})  # first business call -> expired access
        return FakeResp(200, {"ok": True})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    monkeypatch.setattr(api.requests, "post", fake_post)
    token_info = auth.TokenInfo(
        token=make_jwt({"sub": "u", "ssid": "1"}),
        source="manual",
        expires_at=time.time() - 10,
        refresh_token="rt_old",
    )
    notified: list = []
    raw = api.fetch_raw(token_info, "device", on_refresh=notified.append)
    # 1 failed call + 1 refresh + 2 replayed calls
    assert len(calls) == 4
    assert len(notified) == 1
    assert notified[0].refreshed and notified[0].token == fresh_jwt
    assert notified[0].refresh_token == "rt_new"
    assert raw["subscription"] == {"ok": True}
    assert raw["usages"] == {"ok": True}


def test_fetch_raw_raises_auth_error_when_refresh_fails(monkeypatch):
    """401 + dead refresh_token -> single auth error with re-login guidance."""
    class FakeResp:
        status_code = 401

        @property
        def ok(self) -> bool:
            return False

        def json(self) -> dict:
            return {"error": "invalid_grant"}

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr(auth.requests, "post", fake_post)
    monkeypatch.setattr(api.requests, "post", fake_post)
    token_info = auth.TokenInfo(
        token=make_jwt({"sub": "u"}),
        source="manual",
        expires_at=time.time() - 10,
        refresh_token="rt_dead",
    )
    with pytest.raises(api.KimiApiError) as excinfo:
        api.fetch_raw(token_info, "device")
    assert excinfo.value.kind == api.ERROR_AUTH
    assert "重新登录" in str(excinfo.value)


def test_refresh_rejects_oauth_400_invalid_grant_as_unauthorized(monkeypatch):
    """Live behaviour (verified): a dead grant comes back as 400 invalid_grant."""
    class FakeResp:
        status_code = 400

        @property
        def ok(self) -> bool:
            return False

        def json(self) -> dict:
            return {"error": "invalid_grant",
                    "error_description": "The provided authorization grant is invalid"}

    monkeypatch.setattr(auth.requests, "post", lambda *a, **kw: FakeResp())
    with pytest.raises(auth.TokenRefreshError) as excinfo:
        auth.refresh_access_token("rt_dead")
    assert excinfo.value.kind == "unauthorized"


def test_expired_token_without_refresh_token_is_returned_with_hint():
    """No refresh_token -> resolve_token still returns the token for reporting."""
    cfg = {"kimi_token": make_jwt({"sub": "u", "exp": time.time() - 100})}
    tok = auth.resolve_token(cfg, auto_refresh=True)
    assert tok is not None and tok.expired and tok.refresh_token is None


# ------------------------------------------------------------ window labels
def test_window_label_normalizes_units():
    assert models.window_label("TIME_UNIT_MINUTE", 1) == "每分钟"
    assert models.window_label("TIME_UNIT_MINUTE", 300) == "每 5 小时"
    assert models.window_label("TIME_UNIT_HOUR", 5) == "每 5 小时"
    assert models.window_label("TIME_UNIT_HOUR", 24) == "每日"
    assert models.window_label("TIME_UNIT_DAY", 7) == "每周"
    assert models.window_label("TIME_UNIT_WEEK", 1) == "每周"
    assert models.window_label("TIME_UNIT_MONTH", 1) == "每月"
    assert models.window_label("TIME_UNIT_UNKNOWN", 3) == "TIME_UNIT_UNKNOWN"


# --------------------------------------------------------------- normalize
def fixture_raw() -> dict:
    """Shape captured from the real API debug dump (2026-07-25)."""
    return {
        "subscription": {
            "subscription": {
                "subscriptionId": "s1",
                "goods": {"id": "g", "title": "Allegro", "durationDays": 30,
                          "membershipLevel": "x"},
                "currentEndTime": "2099-08-17T00:00:00Z",
                "status": "ok",
                "active": True,
            },
            "balances": [
                {"id": "b1", "feature": "FEATURE_OMNI", "type": "t",
                 "unit": "UNIT_CREDIT", "amountUsedRatio": 0.324,
                 "expireTime": "2099-08-17T08:00:00Z"}
            ],
            "subscribed": True,
            "capabilities": [{"feature": "FEATURE_CODING", "constraint": {"parallelism": 2}}],
        },
        "usages": {
            "usages": [
                {
                    "scope": "FEATURE_CODING",
                    "detail": {"limit": "100", "used": "3", "remaining": "97",
                               "resetTime": "2099-07-31T05:28:29Z"},
                    "limits": [
                        {"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                         "detail": {"limit": "100", "used": "5", "remaining": "95",
                                    "resetTime": "2099-07-25T13:28:29Z"}}
                    ],
                }
            ],
            "totalQuota": {"limit": "100", "used": "32", "remaining": "68"},
        },
    }


def test_normalize_maps_real_response():
    snap = models.normalize(fixture_raw(), token_source="cli")
    assert snap.plan_title == "Allegro"
    assert snap.days_remaining > 0
    assert snap.coding_total == 100
    assert snap.coding_used == 3
    assert abs(snap.usage_ratio - 0.03) < 1e-9
    assert snap.coding_unit == "次"  # fallback, API provides no unit here
    # the 300-minute window must survive and be labelled as 5 hours
    assert len(snap.windows) == 1
    assert snap.windows[0].label == "每 5 小时"
    assert snap.windows[0].remaining == 95
    assert snap.total_quota_limit == 100
    assert snap.total_quota_remaining == 68
    assert snap.balances[0].unit == "credit"
    assert snap.permissions == ["FEATURE_CODING"]
    assert snap.token_source == "cli"


def test_normalize_tolerates_empty_payload():
    snap = models.normalize({"subscription": {}, "usages": {}})
    assert snap.coding_total == 0
    assert snap.windows == []
    assert snap.total_quota_limit is None


def test_normalize_falls_back_to_balance_ratio_without_coding():
    raw = fixture_raw()
    raw["usages"]["usages"] = []
    raw["usages"]["totalQuota"] = None
    snap = models.normalize(raw)
    assert abs(snap.usage_ratio - 0.324) < 1e-9
