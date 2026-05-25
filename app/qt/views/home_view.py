from __future__ import annotations

import collections
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QRectF, QSize
from PySide6.QtGui import (
    QColor, QPainter, QBrush, QLinearGradient, QPen, QDesktopServices, QPixmap,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QGraphicsOpacityEffect,
)

from app.qt.themes.theme import theme_manager, STATUS_COLORS
from app.qt.utils.elevation import apply_elevation
from app.qt.utils.filters import RecordingFilters
from app.qt.utils.typography import DISPLAY_FONT_FAMILY, body_font
from app.utils.logger import logger


class StatCard(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        value: str = "0",
        accent: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_accent_setting = accent
        self._accent = theme_manager.get_color("accent") if accent == "use_theme_accent" else (accent or theme_manager.get_color("accent"))
        self.setMinimumWidth(140)
        self.setFixedHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._setup(icon, title, value)
        apply_elevation(self, level=1)

        theme_manager.themeChanged.connect(self._refresh_colors)

    def _setup(self, icon: str, title: str, value: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 14)
        layout.setSpacing(4)

        icon_row = QHBoxLayout()
        self.icon_lbl = QLabel(icon)
        self.icon_lbl.setStyleSheet("font-size: 22px; background: transparent;")
        icon_row.addWidget(self.icon_lbl)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(
            f"font-size: 28px; font-weight: 800; color: {self._accent}; background: transparent;"
        )
        layout.addWidget(self.value_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            f"font-size: 11px; color: {theme_manager.get_color('text_sec')}; background: transparent;"
        )
        layout.addWidget(self.title_lbl)

    def set_value(self, v: str) -> None:
        self.value_lbl.setText(v)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        c = theme_manager.colors
        r = self.rect()

        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(QBrush(QColor(c["surface"])))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._accent)))
        p.drawRoundedRect(QRectF(2, 1, r.width() - 4, 4), 2, 2)

    def enterEvent(self, event) -> None:  # noqa: N802
        apply_elevation(self, level=1, hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        apply_elevation(self, level=1, hovered=False)
        super().leaveEvent(event)

    def _refresh_colors(self) -> None:
        if self._initial_accent_setting == "use_theme_accent":
            self._accent = theme_manager.get_color("accent")
            
        self.title_lbl.setStyleSheet(
            f"font-size: 11px; color: {theme_manager.get_color('text_sec')}; background: transparent;"
        )
        self.value_lbl.setStyleSheet(
            f"font-size: 28px; font-weight: 800; color: {self._accent}; background: transparent;"
        )
        self.update()
        apply_elevation(self, level=1)


class FeatureCard(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setMinimumWidth(160)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._setup(icon, title, description)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        
        theme_manager.themeChanged.connect(self._refresh_colors)

    def _refresh_colors(self) -> None:
        self.icon_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: 900; "
            f"color: {theme_manager.get_color('accent')}; background: transparent;"
        )

    def _setup(self, icon: str, title: str, description: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        self.icon_lbl = QLabel(icon)
        self.icon_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: 900; "
            f"color: {theme_manager.get_color('accent')}; background: transparent;"
        )
        layout.addWidget(self.icon_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;")
        layout.addWidget(self.title_lbl)

        self.desc_lbl = QLabel(description)
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setProperty("class", "muted")
        layout.addWidget(self.desc_lbl)

    def set_text(self, title: str, description: str):
        self.title_lbl.setText(title)
        self.desc_lbl.setText(description)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_opacity(0.85)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_opacity(1.0)
        super().leaveEvent(event)

    def _animate_opacity(self, target: float) -> None:
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(target)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class QuickActionButton(QPushButton):
    def __init__(
        self,
        icon: str,
        label: str,
        accent: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_accent_setting = accent
        self._accent = theme_manager.get_color("accent") if accent == "use_theme_accent" else (accent or theme_manager.get_color("accent"))
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(f"{icon}  {label}")
        self._refresh_style()
        theme_manager.themeChanged.connect(self._refresh_style)

    def _refresh_style(self):
        if self._initial_accent_setting == "use_theme_accent":
            self._accent = theme_manager.get_color("accent")
            
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._accent};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-weight: 600;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {QColor(self._accent).lighter(115).name()};
            }}
            QPushButton:pressed {{
                background-color: {QColor(self._accent).darker(115).name()};
            }}
        """)


_FAST_COLOR = "#4CAF50"
_MEDIUM_COLOR = "#FF9800"
_SLOW_COLOR = "#F44336"
_BUSY_ALPHA = 0.45
_INTELLIGENCE_CHART_HEIGHT = 130


class QueueBarChart(QWidget):
    _BAR_WIDTH = 18
    _GROUP_GAP = 14
    _BAR_GAP = 4
    _BOTTOM_PAD = 28
    _TOP_PAD = 16
    _LEFT_PAD = 34
    _RIGHT_PAD = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_INTELLIGENCE_CHART_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._disp = [0, 0, 0]
        self._busy = [0, 0, 0]
        self._waiting = 0

        self._rdisp = [0.0, 0.0, 0.0]
        self._rbusy = [0.0, 0.0, 0.0]

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(30)
        self._anim_timer.timeout.connect(self._step_animation)

        theme_manager.themeChanged.connect(self.update)

    def set_data(self, disp: Sequence[int], busy: Sequence[int], waiting: int) -> None:
        self._disp    = list(disp)
        self._busy    = list(busy)
        self._waiting = waiting
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _step_animation(self) -> None:
        speed = 0.22
        settled = True
        for i in range(3):
            for src, rendered in [("_disp", "_rdisp"), ("_busy", "_rbusy")]:
                target = float(getattr(self, src)[i])
                current = getattr(self, rendered)[i]
                diff = target - current
                if abs(diff) < 0.01:
                    getattr(self, rendered)[i] = target
                else:
                    getattr(self, rendered)[i] = current + diff * speed
                    settled = False
        if settled:
            self._anim_timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = theme_manager.colors
        # Safe label lookup — parent() may not have .app if Qt reparented the widget.
        l_intel = {}
        try:
            parent_app = getattr(self.parent(), "app", None)
            if parent_app is not None:
                l_intel = getattr(parent_app, "language_manager", None).language.get("home_view", {})
        except Exception:
            l_intel = {}
        w = self.width()
        h = self.height()
        bottom = h - self._BOTTOM_PAD
        chart_left = self._LEFT_PAD
        chart_right = w - self._RIGHT_PAD
        chart_w = max(chart_right - chart_left, 1)
        chart_h = max(bottom - self._TOP_PAD, 1)

        p.fillRect(self.rect(), QColor(c["surface"]))

        max_val = max(max(self._rdisp + self._rbusy, default=0), 1)

        colors = [_FAST_COLOR, _MEDIUM_COLOR, _SLOW_COLOR]
        labels = [l_intel.get("fast", ""), l_intel.get("med", ""), l_intel.get("slow", "")]
        group_w = self._BAR_WIDTH * 2 + self._BAR_GAP

        total_w = len(labels) * group_w + (len(labels) - 1) * self._GROUP_GAP
        x_start = chart_left + max((chart_w - total_w) // 2, 0)

        font = body_font(9)
        p.setFont(font)
        fm = QFontMetrics(font)
        axis_font = body_font(8)
        axis_fm = QFontMetrics(axis_font)

        for ratio in (1.0, 0.5, 0.0):
            y = self._TOP_PAD + int((1.0 - ratio) * chart_h)
            p.setPen(QPen(QColor(c["border"]), 1))
            p.drawLine(chart_left, y, chart_right, y)

            axis_value = str(int(round(max_val * ratio)))
            p.setPen(QPen(QColor(c["text_muted"])))
            p.setFont(axis_font)
            p.drawText(
                chart_left - axis_fm.horizontalAdvance(axis_value) - 6,
                y + axis_fm.ascent() // 2,
                axis_value,
            )

        p.setFont(font)

        for i, (col, lbl) in enumerate(zip(colors, labels)):
            gx = x_start + i * (group_w + self._GROUP_GAP)

            dh = int(self._rdisp[i] / max_val * chart_h)
            dy = bottom - dh
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(col)))
            p.drawRoundedRect(gx, dy, self._BAR_WIDTH, dh, 3, 3)

            if self._rdisp[i] >= 0.5:
                p.setPen(QPen(QColor(col)))
                disp_val = str(int(round(self._rdisp[i])))
                tw = fm.horizontalAdvance(disp_val)
                p.drawText(gx + (self._BAR_WIDTH - tw) // 2, dy - 3, disp_val)

            bx = gx + self._BAR_WIDTH + self._BAR_GAP
            bh = int(self._rbusy[i] / max_val * chart_h)
            bdy = bottom - bh
            busy_col = QColor(col)
            busy_col.setAlphaF(_BUSY_ALPHA)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(busy_col))
            p.drawRoundedRect(bx, bdy, self._BAR_WIDTH, bh, 3, 3)

            if self._rbusy[i] >= 0.5:
                p.setPen(QPen(busy_col))
                busy_val = str(int(round(self._rbusy[i])))
                tw = fm.horizontalAdvance(busy_val)
                p.drawText(bx + (self._BAR_WIDTH - tw) // 2, bdy - 3, busy_val)

            p.setPen(QPen(QColor(c["text_muted"])))
            lw = fm.horizontalAdvance(lbl)
            p.drawText(gx + (group_w - lw) // 2, bottom + 16, lbl)

        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(x_start - 4, bottom, x_start + total_w + 4, bottom)

        if self._waiting > 0:
            p.setPen(QPen(QColor(c["text_sec"])))
            wait_txt = f"{self._waiting} {l_intel.get('waiting', '')}"
            wait_font = body_font(8)
            wait_fm = QFontMetrics(wait_font)
            p.setFont(wait_font)
            p.drawText(w - wait_fm.horizontalAdvance(wait_txt) - 8, h - 4, wait_txt)


class SparklineChart(QWidget):
    HISTORY = 40
    _TOP_PAD = 16
    _BOTTOM_PAD = 24
    _LEFT_PAD = 34
    _RIGHT_PAD = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_INTELLIGENCE_CHART_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._data: collections.deque[int] = collections.deque(maxlen=self.HISTORY)
        theme_manager.themeChanged.connect(self.update)

    def add_point(self, value: int) -> None:
        self._data.append(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if len(self._data) < 2:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = theme_manager.colors
        w = self.width()
        h = self.height()
        left_pad = self._LEFT_PAD
        right_pad = self._RIGHT_PAD
        top_pad = self._TOP_PAD
        bottom_pad = self._BOTTOM_PAD

        p.fillRect(self.rect(), QColor(c["surface"]))

        data = list(self._data)
        n = len(data)
        max_v = max(data) or 1
        chart_w = max(w - left_pad - right_pad, 1)
        chart_h = max(h - top_pad - bottom_pad, 1)
        step = chart_w / max(n - 1, 1)
        accent = theme_manager.get_color("accent")
        axis_font = body_font(8)
        axis_fm = QFontMetrics(axis_font)

        for ratio in (1.0, 0.5, 0.0):
            y = top_pad + int((1.0 - ratio) * chart_h)
            p.setPen(QPen(QColor(c["border"]), 1))
            p.drawLine(left_pad, y, w - right_pad, y)

            axis_value = str(int(round(max_v * ratio)))
            p.setPen(QPen(QColor(c["text_muted"])))
            p.setFont(axis_font)
            p.drawText(left_pad - axis_fm.horizontalAdvance(axis_value) - 6, y + axis_fm.ascent() // 2, axis_value)

        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF

        pts = []
        for i, v in enumerate(data):
            x = left_pad + i * step
            y = (h - bottom_pad) - (v / max_v) * chart_h
            pts.append(QPointF(x, y))

        grad = QLinearGradient(0, 0, 0, h)
        col_top = QColor(accent)
        col_top.setAlphaF(0.35)
        col_bot = QColor(accent)
        col_bot.setAlphaF(0.0)
        grad.setColorAt(0, col_top)
        grad.setColorAt(1, col_bot)

        fill_pts = [QPointF(pts[0].x(), h - bottom_pad)] + pts + [QPointF(pts[-1].x(), h - bottom_pad)]
        poly = QPolygonF(fill_pts)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPolygon(poly)

        pen = QPen(QColor(accent), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        line_poly = QPolygonF(pts)
        p.drawPolyline(line_poly)

        last_pt = pts[-1]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(accent)))
        p.drawEllipse(last_pt, 4, 4)

        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(left_pad, h - bottom_pad, w - right_pad, h - bottom_pad)


class IntelligenceMonitor(QFrame):
    def __init__(self, app_context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app_context
        self.setProperty("class", "card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        apply_elevation(self, level=1)

        self._setup_ui()
        self._retranslate_ui()
        theme_manager.themeChanged.connect(self._on_theme_changed)

        self.app.event_bus.subscribe("intelligence_cycle", self._on_intelligence_cycle)
        self.app.event_bus.subscribe("language_changed", self._on_language_changed)

    def _on_language_changed(self, topic, new_language) -> None:
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        l_intel = self.app.language_manager.language.get("home_view", {})
        self._title_lbl.setText(l_intel["intelligence_monitor"])
        for lbl, key in self._legend_items:
            lbl.setText(l_intel[key])
        self._busy_lbl.setText(l_intel["busy"])
        self._bar_lbl.setText(l_intel["queue_activity"])
        self._spark_lbl.setText(l_intel["dispatched_per_cycle"])
        for key, label in self._counter_labels.items():
            label.setText(l_intel[key])

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; "
            f"color: {theme_manager.get_color('text')}; background: transparent;"
        )
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()

        self._legend_items = []
        for color, label_key in [(_FAST_COLOR, "fast"), (_MEDIUM_COLOR, "med"), (_SLOW_COLOR, "slow")]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent;")
            lbl = QLabel()
            lbl.setStyleSheet(
                f"color: {theme_manager.get_color('text_muted')}; font-size: 10px; background: transparent;"
            )
            hdr.addWidget(dot)
            hdr.addWidget(lbl)
            self._legend_items.append((lbl, label_key))

        dim_dot = QLabel("●")
        dim_dot.setStyleSheet(f"color: rgba(200,200,200,0.4); font-size: 10px; background: transparent;")
        self._busy_lbl = QLabel()
        self._busy_lbl.setStyleSheet(
            f"color: {theme_manager.get_color('text_muted')}; font-size: 10px; background: transparent;"
        )
        hdr.addWidget(dim_dot)
        hdr.addWidget(self._busy_lbl)

        root.addLayout(hdr)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        bar_col = QVBoxLayout()
        self._bar_lbl = QLabel()
        self._bar_lbl.setStyleSheet(
            f"font-size: 10px; color: {theme_manager.get_color('text_muted')}; background: transparent;"
        )
        bar_col.addWidget(self._bar_lbl)
        self._bar_chart = QueueBarChart(self)
        bar_col.addWidget(self._bar_chart)
        charts_row.addLayout(bar_col, 1)

        sep = QFrame()
        sep.setProperty("class", "divider-v")
        sep.setFixedWidth(1)
        charts_row.addWidget(sep)

        spark_col = QVBoxLayout()
        self._spark_lbl = QLabel()
        self._spark_lbl.setStyleSheet(
            f"font-size: 10px; color: {theme_manager.get_color('text_muted')}; background: transparent;"
        )
        spark_col.addWidget(self._spark_lbl)
        self._sparkline = SparklineChart()
        spark_col.addWidget(self._sparkline)
        charts_row.addLayout(spark_col, 2)

        root.addLayout(charts_row)

        num_row = QHBoxLayout()
        num_row.setSpacing(0)

        self._counters: dict[str, QLabel] = {}
        self._counter_labels: dict[str, QLabel] = {}
        counter_defs = [
            ("counter_disp_fast", _FAST_COLOR),
            ("counter_disp_medium", _MEDIUM_COLOR),
            ("counter_disp_slow", _SLOW_COLOR),
            ("counter_busy_fast", _FAST_COLOR + "88"),
            ("counter_busy_medium", _MEDIUM_COLOR + "88"),
            ("counter_busy_slow", _SLOW_COLOR + "88"),
            ("counter_waiting", theme_manager.get_color("text_sec")),
        ]
        for index, (label_key, color) in enumerate(counter_defs):
            cell = QWidget()
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(8, 4, 8, 4)
            cell_lay.setSpacing(2)

            val_lbl = QLabel("0")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(
                f"font-size: 16px; font-weight: 700; color: {color}; background: transparent;"
            )

            key_lbl = QLabel()
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key_lbl.setStyleSheet(
                f"font-size: 9px; color: {theme_manager.get_color('text_muted')}; background: transparent;"
            )

            cell_lay.addWidget(val_lbl)
            cell_lay.addWidget(key_lbl)
            num_row.addWidget(cell, 1)

            counter_key = label_key.replace("counter_", "")
            self._counters[counter_key] = val_lbl
            self._counter_labels[label_key] = key_lbl

            if index != len(counter_defs) - 1:
                vsep = QFrame()
                vsep.setProperty("class", "divider-v")
                vsep.setFixedWidth(1)
                num_row.addWidget(vsep)

        root.addLayout(num_row)

    def _on_intelligence_cycle(self, topic, data: dict) -> None:
        disp = [data["disp_fast"], data["disp_medium"], data["disp_slow"]]
        busy = [data["busy_fast"], data["busy_medium"], data["busy_slow"]]

        self._bar_chart.set_data(disp, busy, data["waiting"])
        self._sparkline.add_point(data["total_disp"])

        for key in ("disp_fast", "disp_medium", "disp_slow",
                    "busy_fast", "busy_medium", "busy_slow", "waiting"):
            if key in self._counters:
                self._counters[key].setText(str(data.get(key, 0)))

    def _on_theme_changed(self) -> None:
        self._title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; "
            f"color: {theme_manager.get_color('text')}; background: transparent;"
        )
        for lbl in (self._bar_lbl, self._spark_lbl):
            lbl.setStyleSheet(
                f"font-size: 10px; color: {theme_manager.get_color('text_muted')}; background: transparent;"
            )
        self._bar_chart.update()
        self._sparkline.update()
        apply_elevation(self, level=1)


class QtHomeView(QWidget):
    def __init__(self, app_context) -> None:
        super().__init__()
        self.app = app_context
        self.language = self.app.language_manager.language
        self._l = self.language.get("home_page", {})
        self._stat_cards: dict[str, StatCard] = {}
        self._feature_cards: list[FeatureCard] = []

        self.app.event_bus.subscribe("language_changed", self._on_language_changed)
        
        self._setup_ui()
        self._retranslate_ui()
        self._refresh_stats()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(10_000)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start()

        self.app.event_bus.subscribe("update", self._on_recording_event)
        self.app.event_bus.subscribe("add",    self._on_recording_event)
        self.app.event_bus.subscribe("delete", self._on_recording_event)

        theme_manager.themeChanged.connect(self._on_theme_changed)

    def _on_language_changed(self, topic, new_language) -> None:
        self.language = new_language
        self._l = self.language.get("home_page", {})
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        home_page = self.language["home_page"]
        home_view = self.language["home_view"]
        recordings_page = self.language["recordings_page"]
        recording_card = self.language["recording_card"]
        sidebar = self.language["sidebar"]
        about_page = self.language["about_page"]
        settings_page = self.language["settings_page"]
        l_intel = self.language.get("home_view", {})
        self._header_title_lbl.setText(home_page["app_title"])
        self._header_subtitle_lbl.setText(home_page["tagline"])
        self._section_overview_lbl.setText(home_page["stats"])
        
        defs = [
            ("total", home_page["total_rooms"]),
            ("recording", home_page["active_recordings"]),
            ("error", home_page["streams_with_errors"]),
            ("offline", recording_card["offline"]),
        ]
        for key, label in defs:
            if key in self._stat_cards:
                self._stat_cards[key].title_lbl.setText(label)

        self._section_intelligence_lbl.setText(home_view["section_title"])
        self._section_actions_lbl.setText(recordings_page["operations"])
        
        self.btn_add_stream.setText(f"+  {recordings_page['add_record']}")
        self.btn_live_forecast.setText(f"🔮  {home_view['forecast_button']}")
        self.btn_go_recordings.setText(f"▶  {sidebar['recordings']}")
        self.btn_settings.setText(f"✦  {sidebar['settings']}")

        self._section_features_lbl.setText(home_page["main_features"])
        
        features = [
            ("◈", about_page["support_platforms"], home_page["feature_desc_1"]),
            ("◉", home_page["feature_title_1"], home_view["feature_auto_record_desc"]),
            ("✦", settings_page["recording_quality"], about_page["customize_recording"]),
            ("◆", home_page["feature_title_2"], home_page["feature_desc_2"]),
            ("↺", about_page["automatic_transcoding"], settings_page["convert_mp4"]),
            ("◑", f"{sidebar['light_theme']} / {sidebar['dark_theme']}", home_view["feature_theme_switch_desc"]),
        ]
        for i, (_, title, desc) in enumerate(features):
            if i < len(self._feature_cards):
                self._feature_cards[i].set_text(title, desc)
        
        self._tip_text_lbl.setText(
            f"<b>{home_view['tip_prefix']}:</b> "
            + home_view['tip_text'].format(
                live=recordings_page['filter_living'],
                recording=recording_card['recording'],
                offline=recording_card['offline'],
            )
        )
        
        self._intel_monitor._retranslate_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(30, 30, 30, 30)
        self._main_layout.setSpacing(28)

        scroll.setWidget(content)

        self._build_header()
        self._build_stat_cards()
        self._build_intelligence_monitor()
        self._build_quick_actions()
        self._build_feature_cards()
        self._build_tip_section()

        self._main_layout.addStretch()

    def _build_header(self) -> None:
        c = theme_manager.colors

        wrapper = QWidget()
        wrapper.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c['surface']},
                    stop:1 {c['bg']}
                );
                border-radius: 12px;
            }}
        """)
        h_layout = QHBoxLayout(wrapper)
        h_layout.setContentsMargins(24, 20, 24, 20)
        h_layout.setSpacing(16)

        logo = QLabel()
        logo.setFixedSize(56, 56)
        logo.setStyleSheet("background: transparent;")
        logo_path = Path(__file__).resolve().parents[3] / "assets" / "icons" / "streamcapevo_origin_app_icon.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path)).scaled(
                56,
                56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_logo_lbl = logo
        h_layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        title = QLabel(self.language["home_page"]["app_title"])
        self._header_title_lbl = title
        title.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 34px; font-weight: 800; color: {c["accent"]}; background: transparent;'
        )
        text_layout.addWidget(title)

        subtitle = QLabel(
            self.language["home_page"]["tagline"]
        )
        self._header_subtitle_lbl = subtitle
        subtitle.setStyleSheet(
            f"font-size: 14px; color: {c['text_sec']}; background: transparent;"
        )
        text_layout.addWidget(subtitle)
        h_layout.addLayout(text_layout, 1)

        self._main_layout.addWidget(wrapper)
        self._header_wrapper = wrapper

    def _build_stat_cards(self) -> None:
        c = theme_manager.colors

        section_lbl = QLabel(self.language["home_page"]["stats"])
        section_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; letter-spacing: 1px; "
            f"color: {c['text_muted']}; text-transform: uppercase;"
        )
        self._main_layout.addWidget(section_lbl)
        self._section_overview_lbl = section_lbl

        row = QHBoxLayout()
        row.setSpacing(12)

        defs = [
            ("total", "▣", self.language["home_page"]["total_rooms"], "use_theme_accent"),
            ("recording", "◉", self.language["home_page"]["active_recordings"], STATUS_COLORS["recording"]),
            ("error", "!", self.language["home_page"]["streams_with_errors"], STATUS_COLORS["error"]),
            ("offline", "○", self.language["recording_card"]["offline"], STATUS_COLORS["offline"]),
        ]

        for key, icon, label, accent in defs:
            card = StatCard(icon, label, "0", accent=accent)
            row.addWidget(card)
            self._stat_cards[key] = card

        self._main_layout.addLayout(row)

    def _build_intelligence_monitor(self) -> None:
        c = theme_manager.colors

        self._section_intelligence_lbl = QLabel()
        self._section_intelligence_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; letter-spacing: 1px; "
            f"color: {c['text_muted']}; text-transform: uppercase;"
        )
        self._main_layout.addWidget(self._section_intelligence_lbl)


        self._intel_monitor = IntelligenceMonitor(self.app)
        self._main_layout.addWidget(self._intel_monitor)

    def _build_quick_actions(self) -> None:
        c = theme_manager.colors

        section_lbl = QLabel(self.language["recordings_page"]["operations"])
        section_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; letter-spacing: 1px; "
            f"color: {c['text_muted']}; text-transform: uppercase;"
        )
        self._main_layout.addWidget(section_lbl)
        self._section_actions_lbl = section_lbl

        row = QHBoxLayout()
        row.setSpacing(10)

        self.btn_add_stream = QuickActionButton(
            "+", self.language["recordings_page"]["add_record"],
            accent="use_theme_accent",
        )
        self.btn_add_stream.clicked.connect(self._on_add_stream)
        row.addWidget(self.btn_add_stream)

        self.btn_live_forecast = QuickActionButton(
            "🔮", self.language["home_view"]["forecast_button"],
            accent="#4A4A6A",
        )
        self.btn_live_forecast.clicked.connect(self._on_live_forecast)
        row.addWidget(self.btn_live_forecast)

        self.btn_go_recordings = QuickActionButton(
            "▶", self.language["sidebar"]["recordings"],
            accent="#4A4A6A",
        )
        self.btn_go_recordings.clicked.connect(self._on_go_recordings)
        row.addWidget(self.btn_go_recordings)

        self.btn_settings = QuickActionButton(
            "✦", self.language["sidebar"]["settings"],
            accent="#4A4A6A",
        )
        self.btn_settings.clicked.connect(self._on_open_settings)
        row.addWidget(self.btn_settings)

        self._main_layout.addLayout(row)

    def _build_feature_cards(self) -> None:
        c = theme_manager.colors

        section_lbl = QLabel(self.language["home_page"]["main_features"])
        section_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; letter-spacing: 1px; "
            f"color: {c['text_muted']}; text-transform: uppercase;"
        )
        self._main_layout.addWidget(section_lbl)
        self._section_features_lbl = section_lbl

        grid = QGridLayout()
        grid.setSpacing(12)

        features = [
            ("◈", self.language["about_page"]["support_platforms"], self.language["home_page"]["feature_desc_1"]),
            ("◉", self.language["home_page"]["feature_title_1"], self.language["home_view"]["feature_auto_record_desc"]),
            ("✦", self.language["settings_page"]["recording_quality"], self.language["about_page"]["customize_recording"]),
            ("◆", self.language["home_page"]["feature_title_2"], self.language["home_page"]["feature_desc_2"]),
            ("↺", self.language["about_page"]["automatic_transcoding"], self.language["settings_page"]["convert_mp4"]),
            ("◑", f"{self.language['sidebar']['light_theme']} / {self.language['sidebar']['dark_theme']}", self.language["home_view"]["feature_theme_switch_desc"]),
        ]

        for i, (icon, title, desc) in enumerate(features):
            card = FeatureCard(icon, title, desc)
            self._feature_cards.append(card)
            grid.addWidget(card, i // 3, i % 3)

        self._main_layout.addLayout(grid)

    def _build_tip_section(self) -> None:
        c = theme_manager.colors

        tip = QFrame()
        tip.setObjectName("tipFrame")
        tip.setStyleSheet(f"""
            QFrame#tipFrame {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-left: 3px solid {c['accent']};
                border-radius: 8px;
            }}
        """)
        self._tip_frame = tip

        tip_layout = QHBoxLayout(tip)
        tip_layout.setContentsMargins(16, 12, 16, 12)
        tip_layout.setSpacing(12)

        bulb = QLabel("◆")
        bulb.setStyleSheet(
            f"font-size: 16px; font-weight: 900; "
            f"color: {c['accent']}; background: transparent;"
        )
        bulb.setFixedWidth(24)
        tip_layout.addWidget(bulb)

        tip_text = QLabel(
            f"<b>{self.language['home_view']['tip_prefix']}:</b> "
            + self.language['home_view']['tip_text'].format(
                live=self.language['recordings_page']['filter_living'],
                recording=self.language['recording_card']['recording'],
                offline=self.language['recording_card']['offline'],
            )
        )
        tip_text.setWordWrap(True)
        tip_text.setStyleSheet(f"color: {c['text_sec']}; font-size: 13px; background: transparent;")
        tip_layout.addWidget(tip_text, 1)

        self._tip_bulb_lbl = bulb
        self._tip_text_lbl = tip_text
        self._main_layout.addWidget(tip)
        apply_elevation(tip, level=1)

    def _refresh_stats(self) -> None:
        try:
            recordings = self.app.record_manager.recordings
            total = len(recordings)
            rec_count = sum(1 for r in recordings if RecordingFilters.is_recording(r))
            error_count = sum(1 for r in recordings if RecordingFilters.is_error(r))
            offline_count = sum(1 for r in recordings if RecordingFilters.is_offline(r))

            self._stat_cards["total"].set_value(str(total))
            self._stat_cards["recording"].set_value(str(rec_count))
            self._stat_cards["error"].set_value(str(error_count))
            self._stat_cards["offline"].set_value(str(offline_count))
        except (KeyboardInterrupt, SystemError):
            pass
        except Exception as e:
            logger.error(f"HomeView: Error refreshing stats: {e}")

    def _on_recording_event(self, topic, data) -> None:
        QTimer.singleShot(100, self._refresh_stats)

    def _on_add_stream(self) -> None:
        from app.qt.components.add_stream_dialog import QtAddStreamDialog
        dialog = QtAddStreamDialog(self.app, self)
        dialog.exec()

    def _on_live_forecast(self) -> None:
        from app.qt.components.live_forecast_dialog import LiveForecastDialog
        recordings = self.app.record_manager.recordings
        dialog = LiveForecastDialog(self.app, recordings, self)
        dialog.exec()

    def _on_go_recordings(self) -> None:
        if mw := getattr(self.app, "main_window", None):
            mw.show_page("recordings")

    def _on_open_settings(self) -> None:
        if mw := getattr(self.app, "main_window", None):
            mw.show_page("settings")

    def _on_theme_changed(self) -> None:
        c = theme_manager.colors

        self._header_wrapper.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c['surface']},
                    stop:1 {c['bg']}
                );
                border-radius: 12px;
            }}
        """)

        section_style = (
            f"font-size: 12px; font-weight: 700; letter-spacing: 1px; "
            f"color: {c['text_muted']}; text-transform: uppercase;"
        )
        for lbl in (
            self._section_overview_lbl,
            self._section_actions_lbl,
            self._section_features_lbl,
            self._section_intelligence_lbl,
        ):
            lbl.setStyleSheet(section_style)
            
        self._header_title_lbl.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 34px; font-weight: 800; color: {c["accent"]}; background: transparent;'
        )

        self._tip_frame.setStyleSheet(f"""
            QFrame#tipFrame {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-left: 3px solid {c['accent']};
                border-radius: 8px;
            }}
        """)
        self._tip_text_lbl.setStyleSheet(
            f"color: {c['text_sec']}; font-size: 13px; background: transparent;"
        )
        self._tip_bulb_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: 900; "
            f"color: {c['accent']}; background: transparent;"
        )
        apply_elevation(self._tip_frame, level=1)
