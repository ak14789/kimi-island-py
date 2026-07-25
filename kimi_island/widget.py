"""The floating island widget: compact capsule / expanded panel / dot modes."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .models import UsageSnapshot

COMPACT_W, COMPACT_H = 320, 48
EXPANDED_W = 420
DOT_SIZE = 56

COLOR_OK = QColor("#34c759")
COLOR_WARN = QColor("#ffd60a")
COLOR_CRIT = QColor("#ff453a")

_TOKEN_SOURCE_LABELS = {
    "cli": "Kimi CLI（自动读取）",
    "manual": "浏览器 token（本地保存）",
}

PANEL_STYLE = """
QLabel { color: #f2f2f5; background: transparent; }
QLabel#dim { color: #9a9aa2; font-size: 11px; }
QLabel#section { color: #9a9aa2; font-size: 11px; font-weight: 600; }
QLabel#error { color: #ff453a; font-size: 11px; }
QLabel#value { font-size: 12px; font-weight: 600; }
QLabel#title { font-size: 14px; font-weight: 700; }
QProgressBar {
    background: rgba(255,255,255,30); border: none; border-radius: 3px;
    max-height: 6px; min-height: 6px;
}
QProgressBar::chunk { border-radius: 3px; }
QLineEdit {
    background: rgba(255,255,255,18); color: #f2f2f5;
    border: 1px solid rgba(255,255,255,40); border-radius: 6px; padding: 5px 8px;
}
QPushButton {
    background: rgba(255,255,255,26); color: #f2f2f5;
    border: none; border-radius: 6px; padding: 5px 12px;
}
QPushButton:hover { background: rgba(255,255,255,44); }
"""


def _ratio_color(remaining_pct: float, yellow: float, red: float) -> QColor:
    if remaining_pct <= red:
        return COLOR_CRIT
    if remaining_pct <= yellow:
        return COLOR_WARN
    return COLOR_OK


class IslandWidget(QWidget):
    save_token_requested = Signal(str)
    refresh_requested = Signal()
    position_changed = Signal(int, int)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._mode = "compact"
        self._snapshot: Optional[UsageSnapshot] = None
        self._status = "loading"  # loading | ok | error
        self._error_kind = ""
        self._error_text = ""
        self._drag_offset: Optional[QPoint] = None
        self._dragged = False
        self._custom_pos: Optional[QPoint] = None
        if cfg.get("position"):
            self._custom_pos = QPoint(int(cfg["position"][0]), int(cfg["position"][1]))

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFont(QFont("Microsoft YaHei UI", 9))

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self.collapse)

        self._window_rows: list = []   # cached (label_text, bar, value_label)
        self._build_panel()
        self.set_mode("compact")

    def _build_panel(self) -> None:
        self.panel = QWidget(self)
        self.panel.setStyleSheet(PANEL_STYLE)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel("Kimi Island")
        self.title_label.setObjectName("title")
        self.plan_label = QLabel("")
        self.plan_label.setObjectName("dim")
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.plan_label)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        layout.addWidget(self._section("Kimi Code 周用量"))
        self.coding_value = QLabel("--")
        self.coding_value.setObjectName("value")
        layout.addWidget(self.coding_value)
        self.coding_bar = self._bar()
        layout.addWidget(self.coding_bar)
        self.coding_reset = QLabel("")
        self.coding_reset.setObjectName("dim")
        layout.addWidget(self.coding_reset)

        layout.addWidget(self._section("频限窗口"))
        self.windows_box = QVBoxLayout()
        self.windows_box.setSpacing(4)
        layout.addLayout(self.windows_box)

        layout.addWidget(self._section("会员总额度"))
        self.quota_value = QLabel("--")
        self.quota_value.setObjectName("value")
        layout.addWidget(self.quota_value)
        self.quota_bar = self._bar()
        layout.addWidget(self.quota_bar)
        self.quota_detail = QLabel("")
        self.quota_detail.setObjectName("dim")
        self.quota_detail.setWordWrap(True)
        layout.addWidget(self.quota_detail)

        layout.addWidget(self._section("登录凭证"))
        token_row = QHBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("粘贴浏览器 token（可选，覆盖 CLI 凭证）")
        self.token_input.setEchoMode(QLineEdit.Password)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save_token)
        token_row.addWidget(self.token_input, 1)
        token_row.addWidget(save_btn)
        layout.addLayout(token_row)
        self.token_status = QLabel("")
        self.token_status.setObjectName("dim")
        layout.addWidget(self.token_status)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.updated_label = QLabel("")
        self.updated_label.setObjectName("dim")
        layout.addWidget(self.updated_label)

        # Dragging the expanded panel works from any non-interactive area
        # (panel background and labels); buttons and the token input stay
        # clickable as before.
        self.panel.installEventFilter(self)
        for child in self.panel.findChildren(QLabel):
            child.installEventFilter(self)

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def _bar(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)
        return bar

    def set_mode(self, mode: str) -> None:
        changed = mode != self._mode or not self.isVisible()
        self._mode = mode
        if mode == "hidden":
            self.hide()
            return
        if mode == "expanded":
            self.panel.show()
            self._refit_expanded()
        else:
            self.panel.hide()
            size = DOT_SIZE if mode == "dot" else None
            self.resize(size or COMPACT_W, size or COMPACT_H)
        if changed:
            self._reposition()
            self.show()
        self.update()

    def _refit_expanded(self) -> None:
        """Resize the expanded window to fit content without re-showing it."""
        self.panel.adjustSize()
        height = self.panel.sizeHint().height()
        if height != self.height() or self.width() != EXPANDED_W:
            self.resize(EXPANDED_W, height)
            self.panel.setGeometry(0, 0, EXPANDED_W, height)
            self._reposition()

    def _reposition(self) -> None:
        if self._custom_pos is not None:
            self.move(self._custom_pos)
            return
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        self.move(x, geo.y())

    def expand(self) -> None:
        self._collapse_timer.stop()
        self.set_mode("expanded")

    def collapse(self) -> None:
        if self._mode == "expanded":
            self.set_mode("compact")

    def set_dot(self) -> None:
        self.set_mode("dot")

    @property
    def mode(self) -> str:
        return self._mode

    def show_loading(self) -> None:
        self._status = "loading"
        self.update()

    def show_refreshing(self) -> None:
        self.updated_label.setText("刷新中…")

    def show_error(self, kind: str, message: str) -> None:
        self._status = "error"
        self._error_kind = kind
        self._error_text = message
        self.error_label.setText(message)
        if kind in ("no_token", "auth"):
            self.token_status.setText(message)
        if self._mode == "expanded":
            self._refit_expanded()
        self.update()

    def update_snapshot(self, snap: UsageSnapshot) -> None:
        self._snapshot = snap
        self._status = "ok"
        self._error_text = ""

        used_pct = snap.usage_ratio * 100
        color = _ratio_color(
            100 - used_pct,
            float(self._cfg.get("yellow_threshold", 30)),
            float(self._cfg.get("red_threshold", 10)),
        )

        self.plan_label.setText(
            f"{snap.plan_title} · 剩 {snap.days_remaining} 天" if snap.plan_title else ""
        )
        self.coding_value.setText(
            f"已用 {snap.coding_used} / {snap.coding_total} {snap.coding_unit}"
            f"（{used_pct:.0f}%）"
        )
        self._set_bar(self.coding_bar, snap.usage_ratio, color)
        self.coding_reset.setText(
            f"重置时间 {snap.coding_reset_time}" if snap.coding_reset_time else ""
        )

        self._fill_windows(snap)

        if snap.total_quota_limit:
            q_used = snap.total_quota_used or 0
            q_ratio = q_used / snap.total_quota_limit
            self.quota_value.setText(
                f"已用 {q_used} / {snap.total_quota_limit}（{q_ratio * 100:.0f}%）"
            )
            self._set_bar(self.quota_bar, q_ratio, _ratio_color(
                (1 - q_ratio) * 100,
                float(self._cfg.get("yellow_threshold", 30)),
                float(self._cfg.get("red_threshold", 10)),
            ))
            detail = []
            for bal in snap.balances:
                text = f"{bal.label} 已用 {bal.used_ratio * 100:.0f}%"
                if bal.expire_time:
                    text += f" · {bal.expire_time} 到期"
                detail.append(text)
            self.quota_detail.setText("；".join(detail))
        else:
            self.quota_value.setText("无数据")
            self.quota_bar.setValue(0)
            self.quota_detail.setText("")

        source = _TOKEN_SOURCE_LABELS.get(snap.token_source, snap.token_source or "未知")
        self.token_status.setText(f"当前凭证来源：{source}")
        self.error_label.setText("")
        interval = int(self._cfg.get("poll_interval_normal", 60))
        self.updated_label.setText(
            "更新于 "
            + time.strftime("%H:%M:%S", time.localtime(snap.fetched_at))
            + f" · 每 {interval}s 自动刷新"
        )
        if self._mode == "expanded":
            self._refit_expanded()
        self.update()

    def _fill_windows(self, snap: UsageSnapshot) -> None:
        labels = [w.label for w in snap.windows] or ["无频限数据"]
        if [row[0] for row in self._window_rows] != labels:
            while self.windows_box.count():
                item = self.windows_box.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._window_rows = []
            for label_text in labels:
                row = self._make_window_row(label_text)
                self._window_rows.append(row)
        for window, (label_text, bar, value) in zip(snap.windows, self._window_rows):
            used_ratio = (window.used / window.limit) if window.limit else 0.0
            self._set_bar(bar, used_ratio, _ratio_color(
                (1 - used_ratio) * 100,
                float(self._cfg.get("yellow_threshold", 30)),
                float(self._cfg.get("red_threshold", 10)),
            ))
            value.setText(f"已用 {window.used}/{window.limit}")

    def _make_window_row(self, label_text: str):
        if label_text == "无频限数据":
            empty = QLabel(label_text)
            empty.setObjectName("dim")
            empty.installEventFilter(self)
            self.windows_box.addWidget(empty)
            return (label_text, None, QLabel(""))
        else:
            row = QHBoxLayout()
            label = QLabel(label_text)
            label.setObjectName("dim")
            label.installEventFilter(self)
            bar = self._bar()
            bar.setFixedWidth(140)
            value = QLabel("")
            value.setObjectName("value")
            value.installEventFilter(self)
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(bar)
            row.addWidget(value)
            container = QWidget()
            container.setLayout(row)
            self.windows_box.addWidget(container)
            return (label_text, bar, value)

    def _set_bar(self, bar: QProgressBar, used_ratio: float, color: QColor) -> None:
        bar.setValue(int(max(0.0, min(1.0, used_ratio)) * 1000))
        bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color.name()}; }}")

    def _on_save_token(self) -> None:
        token = self.token_input.text().strip()
        if token:
            self.save_token_requested.emit(token)
            self.token_input.clear()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Drag the expanded panel from any non-interactive area (labels/bg)."""
        if self._mode == "expanded" and (obj is self.panel or isinstance(obj, QLabel)):
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                self._dragged = False
                return True
            if etype == QEvent.Type.MouseMove and self._drag_offset is not None:
                target = event.globalPosition().toPoint() - self._drag_offset
                if (target - self.pos()).manhattanLength() > 3:
                    self._dragged = True
                if self._dragged:
                    self.move(target)
                return True
            if etype == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
                if self._dragged:
                    self._custom_pos = self.pos()
                    self.position_changed.emit(self.pos().x(), self.pos().y())
                self._drag_offset = None
                self._dragged = False
                return True
        return super().eventFilter(obj, event)

    def event(self, event) -> bool:  # noqa: N802
        etype = event.type()
        if etype == QEvent.Type.WindowDeactivate and self._mode == "expanded":
            # Clicked outside (e.g. the desktop): collapse shortly after.
            self._collapse_timer.start(300)
        elif etype == QEvent.Type.WindowActivate:
            self._collapse_timer.stop()
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 16 if self._mode == "expanded" else rect.height() / 2
        path = QPainterPath()
        path.addRoundedRect(
            rect.x(), rect.y(), rect.width(), rect.height(), radius, radius
        )
        painter.fillPath(path, QColor(16, 16, 18, 232))
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.drawPath(path)

        if self._mode == "dot":
            self._paint_dot(painter, rect)
        elif self._mode == "compact":
            self._paint_compact(painter, rect)
        painter.end()

    def _state_color(self) -> QColor:
        if self._snapshot is None:
            return QColor("#9a9aa2")
        return _ratio_color(
            (1 - self._snapshot.primary_used_ratio) * 100,
            float(self._cfg.get("yellow_threshold", 30)),
            float(self._cfg.get("red_threshold", 10)),
        )

    def _paint_compact(self, painter: QPainter, rect) -> None:
        painter.setPen(QColor("#f2f2f5"))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        if self._status == "loading":
            text, sub = "Kimi 额度", "加载中…"
        elif self._status == "error":
            text, sub = "Kimi 额度", "点击展开处理"
        elif self._snapshot is not None:
            snap = self._snapshot
            used_pct = snap.primary_used_ratio * 100
            text = f"Kimi 额度  已用 {used_pct:.0f}%"
            if snap.total_quota_limit:
                sub = f"会员总额 {snap.total_quota_used}/{snap.total_quota_limit}"
            else:
                sub = f"编程额度 {snap.coding_used}/{snap.coding_total} {snap.coding_unit}"
        else:
            text, sub = "Kimi 额度", ""
        painter.drawText(rect.adjusted(18, 7, -18, -16), Qt.AlignVCenter, text)
        painter.setPen(QColor("#9a9aa2"))
        font.setBold(False)
        font.setPointSizeF(font.pointSizeF() - 1.5)
        painter.setFont(font)
        painter.drawText(rect.adjusted(18, 18, -18, -6), Qt.AlignVCenter, sub)

        bar_rect = rect.adjusted(18, rect.height() - 10, -18, -5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(bar_rect, 2.5, 2.5)
        if self._snapshot is not None:
            fill = bar_rect.adjusted(0, 0, 0, 0)
            fill.setWidth(int(bar_rect.width() * self._snapshot.primary_used_ratio))
            if fill.width() > 0:
                painter.setBrush(self._state_color())
                painter.drawRoundedRect(fill, 2.5, 2.5)
        elif self._status == "error":
            painter.setBrush(COLOR_CRIT)
            painter.drawRoundedRect(
                bar_rect.adjusted(0, 0, -bar_rect.width() + 14, 0), 2.5, 2.5
            )

    def _paint_dot(self, painter: QPainter, rect) -> None:
        inset = rect.adjusted(6, 6, -6, -6)
        pen = QPen(QColor(255, 255, 255, 40), 4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(inset, 0, 360 * 16)
        if self._snapshot is not None:
            pen.setColor(self._state_color())
            painter.setPen(pen)
            span = int(self._snapshot.primary_used_ratio * 360 * 16)
            painter.drawArc(inset, 90 * 16, span)
        elif self._status == "error":
            pen.setColor(COLOR_CRIT)
            painter.setPen(pen)
            painter.drawArc(inset, 90 * 16, 360 * 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self._dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and self._mode in ("compact", "dot"):
            target = event.globalPosition().toPoint() - self._drag_offset
            if (target - self.pos()).manhattanLength() > 3:
                self._dragged = True
            if self._dragged:
                self.move(target)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self._dragged:
                self._custom_pos = self.pos()
                self.position_changed.emit(self.pos().x(), self.pos().y())
            elif self._mode in ("compact", "dot"):
                self.expand()
            self._drag_offset = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._collapse_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._mode == "expanded":
            self._collapse_timer.start(800)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self._mode == "expanded":
            self.collapse()
        super().keyPressEvent(event)
