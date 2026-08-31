"""Fetch quota data once and print the normalized snapshot (no GUI).

Usage: .venv\\Scripts\\python.exe fetch_once.py [--debug]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from kimi_island import api, auth, config, models


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="dump raw API JSON")
    args = parser.parse_args()

    cfg = config.load_config()
    token = auth.resolve_token(cfg, auto_refresh=True)
    if token is not None and token.refreshed:
        config.save_config(cfg)  # persist the rotated token pair
        print("AUTO_REFRESH: token 临期/过期，已自动刷新成功")
    if token is None:
        print("NO_TOKEN: 未找到 CLI 凭证，也未配置手动 token")
        return 2
    print(f"token_source={token.source} expired={token.expired} "
          f"expires_at={token.expires_at} has_refresh_token={bool(token.refresh_token)}")
    if token.expired:
        # resolve_token already attempted a refresh silently; retry once here
        # to print the precise failure reason for diagnosis.
        if token.refresh_token:
            try:
                token = auth.refresh_access_token(token.refresh_token)
                auth.store_refreshed_token(cfg, token)
                config.save_config(cfg)
                print("AUTO_REFRESH: token 已过期，自动刷新成功")
                print(f"token_source={token.source} expires_at={token.expires_at}")
            except auth.TokenRefreshError as exc:
                print(f"REFRESH_FAILED kind={exc.kind}: {exc}")
                print(
                    "TOKEN_EXPIRED: 登录状态已过期且自动刷新失败。"
                    "请重新登录 Kimi CLI，或重新粘贴 token 与 refresh_token"
                )
                return 3
        else:
            print(
                "TOKEN_EXPIRED: 登录状态已过期，本地没有 refresh_token 无法自动续期。"
                "请重新登录 Kimi CLI，或粘贴新的 token"
            )
            return 3

    dump_dir = config.debug_dir() if args.debug else None
    try:
        raw = api.fetch_raw(token, auth.get_device_id(), dump_dir=dump_dir)
    except api.KimiApiError as exc:
        print(f"FETCH_FAILED kind={exc.kind}: {exc}")
        return 4

    if dump_dir:
        print(f"raw JSON dumped to {dump_dir}")
    snap = models.normalize(raw, token_source=token.source)
    print(json.dumps(dataclasses.asdict(snap), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
