"""
Qt Premium Confirmation Dialog — StreamCapEvo.
A styled dialog for important confirmations (delete, exit, etc.).
"""

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame
)

from app.qt.themes.theme import theme_manager
from app.qt.utils.elevation import apply_elevation
from app.utils.i18n import tr

class QtConfirmDialog(QDialog):
    def __init__(self, title, message, sub_message="", type="warning", parent=None):
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        apply_elevation(self, level=2)
        
        # We don't want standard title bar icons if we want a clean look
        # but for simplicity we keep them for now.
        
        self._setup_ui(title, message, sub_message, type)
        self._apply_styles()
        theme_manager.themeChanged.connect(self._on_theme_changed)

    def _setup_ui(self, title, message, sub_message, type):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # Style colors
        accent = theme_manager.get_color("accent") if type == "warning" else "#F44336" if type == "danger" else "#2196F3"
        
        # Icon / Title row
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {accent};")
        layout.addWidget(title_lbl)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("font-size: 14px; color: #E1E1E1; font-weight: 600;")
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl)

        # Sub-message (optional)
        if sub_message:
            sub_lbl = QLabel(sub_message)
            sub_lbl.setStyleSheet("font-size: 12px; color: #888;")
            sub_lbl.setWordWrap(True)
            layout.addWidget(sub_lbl)

        layout.addSpacing(10)

        # Buttons
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(12)
        
        self.cancel_btn = QPushButton(tr("base.cancel"))
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.confirm_btn = QPushButton(tr("base.confirm"))
        if type == "danger":
            self.confirm_btn.setProperty("class", "danger")
        else:
            self.confirm_btn.setProperty("class", "primary")
        self.confirm_btn.setMinimumWidth(100)
        self.confirm_btn.clicked.connect(self.accept)
        
        btn_lay.addStretch()
        btn_lay.addWidget(self.cancel_btn)
        btn_lay.addWidget(self.confirm_btn)
        
        layout.addLayout(btn_lay)

    def _on_theme_changed(self) -> None:
        apply_elevation(self, level=2)
        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog#confirmDialog {{
                background: {theme_manager.get_color('surface')};
                border: 1px solid {theme_manager.get_color('border')};
                border-radius: 0px;
            }}
            """
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._disable_native_rounded_corners()

    def _disable_native_rounded_corners(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            preference = ctypes.c_int(DWMWCP_DONOTROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except Exception:
            pass

    @classmethod
    def confirm(cls, parent, title, message, sub_message="", type="warning"):
        dialog = cls(title, message, sub_message, type, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted
