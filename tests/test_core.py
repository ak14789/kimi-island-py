"""Unit tests for auth + normalization logic (no network, no Qt)."""
from __future__ import annotations

import base64
import json
import time

from kimi_island import auth, models


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
