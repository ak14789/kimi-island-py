"""Persistent config stored in %APPDATA%\\kimi-island\\config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "kimi_token": "",            # manual browser token (optional override)
    "yellow_threshold": 30,      # remaining % that turns the bar yellow
    "red_threshold": 10,         # remaining % that turns the bar red
    "poll_interval_normal": 60,
    "poll_interval_warning": 30,
    "poll_interval_critical": 15,
    "position": None,            # [x, y] once the user drags the island
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / "kimi-island"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.json"


def debug_dir() -> Path:
    path = config_dir() / "debug"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(config_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update(data)
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update(cfg)
    config_file().write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
