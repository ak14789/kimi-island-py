"""Background polling thread with adaptive interval and error backoff."""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from . import api, auth, models


class Poller(QThread):
    fetched = Signal(object)      # models.UsageSnapshot
    failed = Signal(str, str)     # kind, message ("no_token" | "auth" | "network" | ...)

    def __init__(
        self,
        config_provider: Callable[[], dict],
        debug_dump: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._config_provider = config_provider
        self._debug_dump = debug_dump
        self._wake = threading.Event()
        self._stopped = False

    def run(self) -> None:
        from . import config as config_mod  # late import keeps module Qt-free

        backoff = 0
        while not self._stopped:
            cfg = self._config_provider()
            interval = float(cfg.get("poll_interval_normal", 60))
            token = auth.resolve_token(cfg)
            if token is None:
                self.failed.emit("no_token", "未找到登录凭证：请登录 Kimi CLI 或粘贴浏览器 token")
            elif token.expired:
                self.failed.emit("auth", "登录状态已过期，请重新获取 Token")
            else:
                try:
                    dump_dir = config_mod.debug_dir() if self._debug_dump else None
                    raw = api.fetch_raw(token, auth.get_device_id(), dump_dir=dump_dir)
                    snap = models.normalize(raw, token_source=token.source)
                    self.fetched.emit(snap)
                    backoff = 0
                    remaining_pct = (1.0 - snap.primary_used_ratio) * 100
                    if remaining_pct <= float(cfg.get("red_threshold", 10)):
                        interval = float(cfg.get("poll_interval_critical", 15))
                    elif remaining_pct <= float(cfg.get("yellow_threshold", 30)):
                        interval = float(cfg.get("poll_interval_warning", 30))
                except api.KimiApiError as exc:
                    self.failed.emit(exc.kind, str(exc))
                    if exc.kind == api.ERROR_NETWORK:
                        backoff = min(backoff + 1, 4)
                        interval = min(30.0 * (2 ** backoff), 300.0)
                    else:
                        interval = 60.0
            self._wake.wait(interval)
            self._wake.clear()

    def refresh_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()
