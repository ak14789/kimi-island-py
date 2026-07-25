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
    token = auth.resolve_token(cfg)
    if token is None:
        print("NO_TOKEN: 未找到 CLI 凭证，也未配置手动 token")
        return 2
    print(f"token_source={token.source} expired={token.expired} "
          f"expires_at={token.expires_at}")
    if token.expired:
        print("TOKEN_EXPIRED: 登录状态已过期，请重新登录或粘贴新 token")
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
