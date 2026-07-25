"""Render the island widget offscreen with fixture data and save screenshots."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kimi_island import models
from kimi_island.widget import IslandWidget

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tests.test_core import fixture_raw  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "."


def main() -> None:
    app = QApplication([])
    widget = IslandWidget({"yellow_threshold": 30, "red_threshold": 10})
    snap = models.normalize(fixture_raw(), token_source="cli")
    widget.update_snapshot(snap)

    widget.set_mode("compact")
    widget.grab().save(os.path.join(OUT, "smoke-compact.png"))

    widget.set_mode("expanded")
    app.processEvents()
    widget.set_mode("expanded")
    widget.grab().save(os.path.join(OUT, "smoke-expanded.png"))

    widget.set_mode("dot")
    widget.grab().save(os.path.join(OUT, "smoke-dot.png"))

    widget.show_error("auth", "登录状态已过期，请重新获取 Token")
    widget.set_mode("compact")
    widget.grab().save(os.path.join(OUT, "smoke-error.png"))

    print("expanded size:", widget.width(), "x", widget.height())
    print("screenshots written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
