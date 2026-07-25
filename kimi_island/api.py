"""Kimi internal web API client (Connect protocol over HTTP POST)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

from .auth import TokenInfo

BASE_URL = "https://www.kimi.com"
SUBSCRIPTION_URL = (
    f"{BASE_URL}/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscription"
)
USAGES_URL = f"{BASE_URL}/apiv2/kimi.gateway.billing.v1.BillingService/GetUsages"

ERROR_AUTH = "auth"
ERROR_NETWORK = "network"
ERROR_HTTP = "http"
ERROR_PARSE = "parse"


class KimiApiError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def build_headers(token_info: TokenInfo, device_id: str) -> dict:
    claims = token_info.claims()
    user_id = claims.get("sub")
    if not user_id:
        raise KimiApiError(ERROR_AUTH, "Token 中缺少 sub (user_id)，请重新获取")
    session_id = str(claims.get("ssid") or "0")
    return {
        "Authorization": f"Bearer {token_info.token}",
        "x-msh-device-id": device_id,
        "x-msh-session-id": session_id,
        "x-traffic-id": str(user_id),
        "x-msh-platform": "web",
        "x-msh-version": "1.0.0",
        "x-language": "zh-CN",
        "r-timezone": "Asia/Shanghai",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Referer": "https://www.kimi.com/code/console",
        "Origin": "https://www.kimi.com",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "connect-protocol-version": "1",
    }


def _post(url: str, headers: dict, payload: dict) -> dict:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        raise KimiApiError(ERROR_NETWORK, f"网络请求失败: {exc}") from exc
    if resp.status_code == 401:
        raise KimiApiError(ERROR_AUTH, "登录状态已过期，请重新获取 Token")
    if not resp.ok:
        raise KimiApiError(ERROR_HTTP, f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise KimiApiError(ERROR_PARSE, f"响应解析失败: {exc}") from exc


def fetch_raw(
    token_info: TokenInfo,
    device_id: str,
    dump_dir: Optional[Path] = None,
) -> dict:
    """Fetch subscription + usages. Returns {"subscription": ..., "usages": ...}."""
    headers = build_headers(token_info, device_id)
    subscription = _post(SUBSCRIPTION_URL, headers, {})
    usages = _post(USAGES_URL, headers, {"scope": ["FEATURE_CODING"]})
    raw = {"subscription": subscription, "usages": usages}
    if dump_dir is not None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name, data in raw.items():
            (dump_dir / f"{name}-{stamp}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return raw
