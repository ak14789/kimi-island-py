"""Application entry: island widget + poller + system tray."""
from __future__ import annotations

import argparse
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config as config_mod
from .poller import Poller
from .widget import IslandWidget


def make_tray_icon() -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(16, 16, 18, 240))
    painter.setPen(QColor(255, 255, 255, 40))
    painter.drawRoundedRect(2, 8, 28, 16, 8, 8)
    painter.setPen(QColor("#34c759"))
    painter.drawText(pix.rect(), Qt.AlignCenter, "K")
    painter.end()
    return QIcon(pix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="dump raw API JSON")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    state = {"cfg": config_mod.load_config()}
    island = IslandWidget(state["cfg"])
    poller = Poller(lambda: state["cfg"], debug_dump=args.debug)

    poller.fetched.connect(island.update_snapshot)
    poller.failed.connect(island.show_error)
    island.refresh_requested.connect(poller.refresh_now)
    island.refresh_requested.connect(island.show_refreshing)

    def on_save_token(token: str) -> None:
        state["cfg"]["kimi_token"] = token
        config_mod.save_config(state["cfg"])
        poller.refresh_now()

    def on_save_refresh_token(token: str) -> None:
        state["cfg"]["kimi_refresh_token"] = token
        config_mod.save_config(state["cfg"])
        poller.refresh_now()

    def on_position(x: int, y: int) -> None:
        state["cfg"]["position"] = [x, y]
        config_mod.save_config(state["cfg"])

    island.save_token_requested.connect(on_save_token)
    island.save_refresh_token_requested.connect(on_save_refresh_token)
    island.position_changed.connect(on_position)

    tray = QSystemTrayIcon(make_tray_icon(), parent=app)
    tray.setToolTip("Kimi Island Py")
    menu = QMenu()

    def on_fetched(snap) -> None:
        tray.setToolTip(
            f"Kimi 总额度已用 {snap.primary_used_ratio * 100:.0f}% · "
            + time.strftime("更新于 %H:%M:%S", time.localtime(snap.fetched_at))
        )

    poller.fetched.connect(on_fetched)

    def toggle_visibility() -> None:
        if island.isVisible():
            island.set_mode("hidden")
        else:
            island.set_mode("compact")

    action_toggle = menu.addAction("显示 / 隐藏")
    action_toggle.triggered.connect(toggle_visibility)
    action_dot = menu.addAction("收起为圆点")

    def toggle_dot() -> None:
        if island.mode == "dot":
            island.set_mode("compact")
        else:
            island.set_dot()

    action_dot.triggered.connect(toggle_dot)
    menu.aboutToShow.connect(
        lambda: action_dot.setText(
            "展开为胶囊" if island.mode == "dot" else "收起为圆点"
        )
    )
    action_refresh = menu.addAction("立即刷新")
    action_refresh.triggered.connect(poller.refresh_now)
    menu.addSeparator()
    action_quit = menu.addAction("退出")

    def on_quit() -> None:
        poller.stop()
        poller.wait(3000)
        app.quit()

    action_quit.triggered.connect(on_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: toggle_visibility()
        if reason == QSystemTrayIcon.DoubleClick
        else None
    )
    tray.show()

    island.show_loading()
    poller.start()
    exit_code = app.exec()
    poller.stop()
    poller.wait(3000)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
