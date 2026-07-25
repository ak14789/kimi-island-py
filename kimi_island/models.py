"""Normalize raw Kimi API responses into a UI-friendly snapshot.

Unlike the reference Tauri project, rate-limit windows are NOT mapped onto
fixed rpm/tpm/rpd slots. Each window is labelled from its actual
time_unit + duration, so a 5-hour window or a weekly window is displayed
correctly instead of being dropped or mislabelled.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_UNIT_ZH = {
    "MINUTE": "分钟",
    "HOUR": "小时",
    "DAY": "天",
    "WEEK": "周",
    "MONTH": "个月",
}
_UNIT_ZH_SINGULAR = {
    "MINUTE": "每分钟",
    "HOUR": "每小时",
    "DAY": "每日",
    "WEEK": "每周",
    "MONTH": "每月",
}


def window_label(time_unit: str, duration: int) -> str:
    unit = (time_unit or "").replace("TIME_UNIT_", "").upper()
    # Normalize to the largest clean unit: 300 minutes -> 5 hours, etc.
    if unit == "MINUTE" and duration % 60 == 0:
        unit, duration = "HOUR", duration // 60
    if unit == "HOUR" and duration % 24 == 0:
        unit, duration = "DAY", duration // 24
    if unit == "DAY" and duration % 7 == 0:
        unit, duration = "WEEK", duration // 7
    if unit in _UNIT_ZH_SINGULAR and duration <= 1:
        return _UNIT_ZH_SINGULAR[unit]
    if unit in _UNIT_ZH:
        return f"每 {duration} {_UNIT_ZH[unit]}"
    return time_unit or "未知窗口"


_FRIENDLY_UNITS = {
    "UNIT_CREDIT": "credit",
    "UNIT_COUNT": "次",
}


def friendly_unit(unit: str) -> str:
    return _FRIENDLY_UNITS.get(unit, unit)


_FRIENDLY_FEATURES = {
    "FEATURE_OMNI": "会员额度",
    "FEATURE_CODING": "编程额度",
    "FEATURE_CHAT": "聊天额度",
}


def friendly_feature(feature: str) -> str:
    if feature in _FRIENDLY_FEATURES:
        return _FRIENDLY_FEATURES[feature]
    return feature.replace("FEATURE_", "").replace("_", " ").title()


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class RateWindow:
    label: str
    limit: int
    remaining: int
    reset_time: str = ""

    @property
    def used(self) -> int:
        return max(self.limit - self.remaining, 0)


@dataclass
class BalanceInfo:
    feature: str
    unit: str
    used_ratio: float
    expire_time: str = ""

    @property
    def label(self) -> str:
        return friendly_feature(self.feature)


@dataclass
class UsageSnapshot:
    plan_title: str = ""
    end_time: str = ""
    days_remaining: int = 0
    coding_used: int = 0
    coding_total: int = 0
    coding_unit: str = "次"
    coding_reset_time: str = ""
    usage_ratio: float = 0.0  # used / total for the coding quota
    windows: list = field(default_factory=list)        # list[RateWindow]
    balances: list = field(default_factory=list)       # list[BalanceInfo]
    total_quota_limit: Optional[int] = None
    total_quota_remaining: Optional[int] = None
    permissions: list = field(default_factory=list)    # list[str]
    token_source: str = ""
    fetched_at: float = field(default_factory=time.time)

    @property
    def remaining_ratio(self) -> float:
        return max(0.0, min(1.0, 1.0 - self.usage_ratio))

    @property
    def total_quota_used(self) -> Optional[int]:
        if self.total_quota_limit is None or self.total_quota_remaining is None:
            return None
        return max(self.total_quota_limit - self.total_quota_remaining, 0)

    @property
    def total_used_ratio(self) -> Optional[float]:
        """Used ratio of the membership-wide quota (None when unavailable)."""
        used = self.total_quota_used
        if used is None or not self.total_quota_limit:
            return None
        return max(0.0, min(1.0, used / self.total_quota_limit))

    @property
    def primary_used_ratio(self) -> float:
        """The headline metric: membership total quota, coding quota as fallback."""
        total = self.total_used_ratio
        return total if total is not None else self.usage_ratio


def _parse_reset_time(raw: str) -> str:
    """RFC3339 -> short local display string; pass through on failure."""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%m-%d %H:%M")
    except ValueError:
        return raw


def normalize(raw: dict, token_source: str = "") -> UsageSnapshot:
    sub = raw.get("subscription") or {}
    usages_resp = raw.get("usages") or {}
    snap = UsageSnapshot(token_source=token_source)

    subscription = sub.get("subscription") or {}
    goods = subscription.get("goods") or {}
    snap.plan_title = goods.get("title") or ""
    snap.end_time = subscription.get("currentEndTime") or ""
    if snap.end_time:
        try:
            end = datetime.fromisoformat(snap.end_time.replace("Z", "+00:00"))
            snap.days_remaining = max(
                (end - datetime.now(timezone.utc)).days, 0
            )
        except ValueError:
            pass

    for bal in sub.get("balances") or []:
        snap.balances.append(
            BalanceInfo(
                feature=bal.get("feature") or "",
                unit=friendly_unit(bal.get("unit") or ""),
                used_ratio=float(bal.get("amountUsedRatio") or 0.0),
                expire_time=_parse_reset_time(bal.get("expireTime") or ""),
            )
        )

    snap.permissions = [
        c.get("feature") or "" for c in (sub.get("capabilities") or []) if c.get("feature")
    ]

    coding = None
    for usage in usages_resp.get("usages") or []:
        if usage.get("scope") == "FEATURE_CODING":
            coding = usage
            break

    # Unit: prefer an explicit unit on the coding usage/balance; never hardcode.
    coding_unit = ""
    if coding:
        coding_unit = (coding.get("detail") or {}).get("unit") or ""
    if not coding_unit:
        for bal in snap.balances:
            if bal.feature == "FEATURE_CODING" and bal.unit:
                coding_unit = bal.unit
                break
    snap.coding_unit = coding_unit or "次"

    if coding:
        detail = coding.get("detail") or {}
        limit = _to_int(detail.get("limit"))
        remaining = _to_int(detail.get("remaining"))
        snap.coding_total = limit
        snap.coding_used = max(limit - remaining, 0)
        snap.coding_reset_time = _parse_reset_time(detail.get("resetTime") or "")
        snap.usage_ratio = (snap.coding_used / limit) if limit > 0 else 0.0
        for item in coding.get("limits") or []:
            window = item.get("window") or {}
            item_detail = item.get("detail") or {}
            snap.windows.append(
                RateWindow(
                    label=window_label(
                        window.get("timeUnit") or "", _to_int(window.get("duration"), 1)
                    ),
                    limit=_to_int(item_detail.get("limit")),
                    remaining=_to_int(item_detail.get("remaining")),
                    reset_time=_parse_reset_time(item_detail.get("resetTime") or ""),
                )
            )

    total_quota = usages_resp.get("totalQuota")
    if total_quota:
        snap.total_quota_limit = _to_int(total_quota.get("limit"))
        snap.total_quota_remaining = _to_int(total_quota.get("remaining"))

    # Fallback ratio from balances when no coding usage detail exists.
    if not coding and snap.balances:
        snap.usage_ratio = max(0.0, min(1.0, snap.balances[0].used_ratio))

    return snap
