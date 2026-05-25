"""
Qt Sidebar navigation for StreamCapEvo.

Replaces the Flet NavigationSidebar / LeftNavigationMenu with a
PySide6 implementation using QPushButtons inside a QVBoxLayout.
"""

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.qt.themes.theme import theme_manager
from app.qt.utils.iconography import apply_button_icon, apply_label_icon
from app.qt.utils.typography import BODY_FONT_FAMILY, DISPLAY_FONT_FAMILY


class SidebarItem(QPushButton):
    """A single navigation item in the sidebar."""

    def __init__(self, icon_name: str, label: str, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.icon_name = icon_name
        self._selected = False
        self._hovered = False
        self._icon_initialized = False
        self._label_text = label

        self.setProperty("class", "sidebar-item")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setToolTip(label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)
        self._layout = layout

        self.icon_label = QLabel()
        self.icon_label.setFixedWidth(24)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 18px; background: transparent;")
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(label)
        self.text_label.setStyleSheet(
            f'background: transparent; font-family: "{BODY_FONT_FAMILY}"; font-size: 13px;'
        )
        layout.addWidget(self.text_label)
        layout.addStretch()
        self._refresh_visuals()

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        if self._selected == value and self._icon_initialized:
            return
        self._selected = value
        if self.property("selected") != ("true" if value else "false"):
            self.setProperty("selected", "true" if value else "false")
            self.style().unpolish(self)
            self.style().polish(self)
        self._refresh_visuals()

    def refresh_theme_icon(self) -> None:
        self._refresh_visuals()

    def _refresh_visuals(self) -> None:
        icon_color = (
            theme_manager.get_color("accent")
            if self._selected or self._hovered
            else theme_manager.get_color("text_sec")
        )
        text_color = (
            theme_manager.get_color("accent")
            if self._selected
            else theme_manager.get_color("text")
            if self._hovered
            else theme_manager.get_color("text_sec")
        )
        apply_label_icon(self.icon_label, self.icon_name, size=18, color=icon_color)
        self.text_label.setStyleSheet(
            f'background: transparent; font-family: "{BODY_FONT_FAMILY}"; font-size: 13px; color: {text_color};'
        )
        self._icon_initialized = True

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._refresh_visuals()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._refresh_visuals()
        super().leaveEvent(event)

    def set_label(self, text: str):
        """Update the displayed label text (for language changes)."""
        self._label_text = text
        self.text_label.setText(text)
        self.setToolTip(text)

    def set_compact(self, compact: bool):
        self.text_label.setVisible(not compact)
        if compact:
            self._layout.setContentsMargins(8, 0, 8, 0)
            self._layout.setSpacing(0)
            self.icon_label.setFixedWidth(44)
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self._layout.setContentsMargins(12, 0, 12, 0)
            self._layout.setSpacing(12)
            self.icon_label.setFixedWidth(24)
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)


class Sidebar(QFrame):
    """
    Left navigation sidebar with navigation items.

    Signals:
        page_changed(str): Emitted when a navigation item is clicked.
        collapsed_changed(bool, str): bool state + source ("manual" | "auto").
    """

    page_changed = Signal(str)
    collapsed_changed = Signal(bool, str)

    EXPANDED_WIDTH = 180
    COLLAPSED_WIDTH = 64
    ANIMATION_MS = 160

    NAV_ITEMS = [
        ("home", "Home", "home"),
        ("stats", "Stats", "stats"),
        ("recordings", "Recordings", "recordings"),
        ("settings", "Settings", "settings"),
        ("logs", "Logs", "logs"),
        ("about", "About", "about"),
    ]

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.setProperty("class", "sidebar")
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setMinimumHeight(400)

        self._items: list[SidebarItem] = []
        self._selected_index = 0
        self._collapsed = False
        self._auto_forced = False
        self._label_cache: dict[str, str] = {}
        self._width_anim = QVariantAnimation(self)
        self._width_anim.setDuration(self.ANIMATION_MS)
        self._width_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_anim.valueChanged.connect(self._on_width_anim_value)

        self._setup_ui()
        self._load_translations()
        self._select_item(0)
        self._apply_collapse_visual_state()

        self.app.event_bus.subscribe("language_changed", self._retranslate_ui)
        theme_manager.themeChanged.connect(self._on_theme_changed)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_auto_forced(self, forced: bool) -> None:
        self._auto_forced = forced
        self.toggle_btn.setEnabled(not forced)
        self._refresh_toggle_tooltip()

    def set_collapsed(self, collapsed: bool, source: str = "manual", animate: bool = True) -> None:
        if collapsed == self._collapsed and self.width() == self._target_width(collapsed):
            self._refresh_toggle_icon()
            return

        self._collapsed = collapsed
        self._apply_collapse_visual_state()
        self._animate_to_width(self._target_width(collapsed), animate=animate)
        self.collapsed_changed.emit(self._collapsed, source)

    def _retranslate_ui(self, *args):
        self._load_translations()
        self._refresh_theme_button_text()
        self._refresh_toggle_tooltip()

    def _load_translations(self):
        """Load translated labels from the app context."""
        try:
            language = self.app.language_manager.language
            sidebar_labels = language.get("sidebar", {})

            keys_map = {
                "home": "home",
                "stats": "stats",
                "recordings": "recordings",
                "settings": "settings",
                "logs": "logs",
                "about": "about",
            }

            translated = {}
            for key, page_name in keys_map.items():
                if key in sidebar_labels:
                    translated[page_name] = sidebar_labels[key]

            self._label_cache = translated
            if translated:
                self.update_labels(translated)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 12)
        layout.setSpacing(2)

        # Header (title + collapse toggle)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 10)
        header_layout.setSpacing(8)

        title_wrap = QWidget()
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        self.title_lbl = QLabel("StreamCapEvo")
        self.title_lbl.setProperty("class", "heading")
        self.title_lbl.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 18px; font-weight: 700; color: {theme_manager.get_color("accent")}; background: transparent;'
        )
        title_layout.addWidget(self.title_lbl)

        self.subtitle_lbl = QLabel("Origin")
        self.subtitle_lbl.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 11px; font-weight: 600; color: {theme_manager.get_color("text_sec")}; background: transparent;'
        )
        title_layout.addWidget(self.subtitle_lbl)

        self.title_wrap = title_wrap
        header_layout.addWidget(self.title_wrap, 1)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setProperty("class", "sidebar-toggle")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        header_layout.addWidget(self.toggle_btn)

        layout.addWidget(header)
        self._header = header

        # Navigation items
        for icon_name, label, name in self.NAV_ITEMS:
            item = SidebarItem(icon_name, label, name, self)
            item.clicked.connect(lambda checked=False, n=name: self._on_item_clicked(n))
            self._items.append(item)
            layout.addWidget(item)

        layout.addStretch()

        # Theme Toggle
        self.theme_btn = QPushButton("Dark")
        self.theme_btn.setProperty("class", "sidebar-item")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.setFixedHeight(44)
        layout.addWidget(self.theme_btn)

    def _on_width_anim_value(self, value):
        width = int(value)
        self.setFixedWidth(width)

    def _animate_to_width(self, target: int, animate: bool) -> None:
        self._width_anim.stop()
        if not animate:
            self.setFixedWidth(target)
            return

        self._width_anim.setStartValue(self.width())
        self._width_anim.setEndValue(target)
        self._width_anim.start()

    def _target_width(self, collapsed: bool) -> int:
        return self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH

    def _on_toggle_clicked(self):
        self.set_collapsed(not self._collapsed, source="manual", animate=True)

    def _refresh_toggle_icon(self):
        icon_name = "expand" if self._collapsed else "collapse"
        apply_button_icon(
            self.toggle_btn,
            icon_name,
            size=14,
            color=theme_manager.get_color("text_sec"),
            fallback_text=True,
        )

    def _refresh_toggle_tooltip(self):
        sidebar_labels = self.app.language_manager.language.get("sidebar", {})
        expand = sidebar_labels.get("expand_sidebar", "Expand sidebar")
        collapse = sidebar_labels.get("collapse_sidebar", "Collapse sidebar")
        forced = sidebar_labels.get("sidebar_compact_auto", "Compact mode enabled for narrow window")

        if self._auto_forced:
            self.toggle_btn.setToolTip(forced)
            return
        self.toggle_btn.setToolTip(expand if self._collapsed else collapse)

    def _apply_collapse_visual_state(self):
        self.title_wrap.setVisible(not self._collapsed)
        for item in self._items:
            item.set_compact(self._collapsed)

        self._refresh_theme_button_text()
        self._refresh_toggle_icon()
        self._refresh_toggle_tooltip()

    def _refresh_theme_button_text(self):
        sidebar_labels = self.app.language_manager.language.get("sidebar", {})
        if theme_manager.is_dark:
            text = sidebar_labels.get("dark_theme", "Dark")
            icon_name = "theme_dark"
        else:
            text = sidebar_labels.get("light_theme", "Light")
            icon_name = "theme_light"

        apply_button_icon(
            self.theme_btn,
            icon_name,
            size=14,
            color=theme_manager.get_color("text_sec"),
            fallback_text=True,
        )
        self.theme_btn.setText("" if self._collapsed else text)
        self.theme_btn.setToolTip(text)

    def _on_item_clicked(self, name: str):
        """Handle navigation item click."""
        for i, item in enumerate(self._items):
            if item.name == name:
                self._select_item(i)
                break
        self.page_changed.emit(name)

    def _select_item(self, index: int):
        """Visually select the item at the given index."""
        for i, item in enumerate(self._items):
            item.selected = (i == index)
        self._selected_index = index

    def select_page(self, name: str):
        """Programmatically select a page by name."""
        for i, item in enumerate(self._items):
            if item.name == name:
                self._select_item(i)
                return

    def update_labels(self, labels: dict[str, str]):
        """Update sidebar labels for i18n."""
        for item in self._items:
            if item.name in labels:
                item.set_label(labels[item.name])

    def set_theme_text(self, text: str):
        """Update the theme toggle button label."""
        if self._collapsed:
            self.theme_btn.setText("")
        else:
            self.theme_btn.setText(text)

    def _on_theme_changed(self):
        self.title_lbl.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 18px; font-weight: 700; color: {theme_manager.get_color("accent")}; background: transparent;'
        )
        self.subtitle_lbl.setStyleSheet(
            f'font-family: "{DISPLAY_FONT_FAMILY}"; font-size: 11px; font-weight: 600; color: {theme_manager.get_color("text_sec")}; background: transparent;'
        )
        for item in self._items:
            item.refresh_theme_icon()
        self._refresh_theme_button_text()
