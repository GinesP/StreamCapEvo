"""
Qt Toast Notification System for StreamCapEvo.
Provides floating, auto-dismissing alerts in the corner of the window.
"""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QSize
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QHBoxLayout,
    QFrame,
    QVBoxLayout,
    QGraphicsOpacityEffect
)
from PySide6.QtGui import QColor
from app.qt.utils.iconography import apply_label_icon, icon_glyph


class ToastWidget(QFrame):
    """
    A single toast notification widget.
    """
    def __init__(self, message, toast_type="info", parent=None):
        super().__init__(parent)
        self.message = message
        self.toast_type = toast_type
        
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        self._setup_ui()
        
    def _setup_ui(self):
        """
        Setup nested UI to support both drop shadow and opacity fading.
        The shadow is on the inner 'content' frame, the opacity is on 'self'.
        """
        # Outer wrapper needs to be transparent for the shadow margins
        self.setObjectName("toastWrapper")
        # Ensure we don't inherit global background
        self.setStyleSheet("background: transparent; border: none;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)  # Room for the shadow
        
        self.content = QFrame(self)
        self.content.setObjectName("toastContent")
        main_layout.addWidget(self.content)
        
        # Style based on type
        colors = {
            "info": "#2D2D2D",
            "success": "#2E7D32",
            "error": "#C62828",
            "warning": "#F9A825"
        }
        accent = colors.get(self.toast_type, colors["info"])
        
        # Inner frame styling
        self.content.setStyleSheet(f"""
            QFrame#toastContent {{
                background-color: {accent};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
            }}
            QLabel {{
                color: #FFFFFF;
                background: transparent;
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        
        content_layout = QHBoxLayout(self.content)
        content_layout.setContentsMargins(15, 12, 15, 12)
        content_layout.setSpacing(12)
        
        # Icon
        icons = {
            "info": icon_glyph("info"),
            "success": icon_glyph("success"),
            "error": icon_glyph("error"),
            "warning": icon_glyph("warning")
        }
        icon_label = QLabel(icons.get(self.toast_type, icon_glyph("info")))
        apply_label_icon(icon_label, self.toast_type if self.toast_type in ("info", "success", "error", "warning") else "info", size=14, color="#FFFFFF")
        content_layout.addWidget(icon_label)
        
        # Message
        self.label = QLabel(self.message)
        self.label.setWordWrap(True)
        content_layout.addWidget(self.label)
        
        # Apply drop shadow to the INNER frame
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self.content)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 3)
        self.content.setGraphicsEffect(shadow)
        
        # Apply opacity effect to the OUTER widget for fading
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
    def fade_in(self, duration=300):
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(duration)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.start()
        
    def fade_out(self, duration=500, callback=None):
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(duration)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InCubic)
        if callback:
            self.animation.finished.connect(callback)
        self.animation.start()


class QtToastManager:
    """
    Manages a queue of toasts and displays them stacked in the corner.
    """
    def __init__(self, main_window):
        self.main_window = main_window
        self.active_toasts = []
        self.spacing = 10
        self.margin = 20
        
    def show_toast(self, message, toast_type="info", duration=4000):
        toast = ToastWidget(message, toast_type, self.main_window)
        toast.show()
        toast.fade_in()
        
        self.active_toasts.append(toast)
        self._reposition_toasts()
        
        # Auto-dismiss
        timer = QTimer(toast)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._remove_toast(toast))
        timer.start(duration)
        
    def _remove_toast(self, toast):
        if toast in self.active_toasts:
            toast.fade_out(callback=lambda: self._on_fade_out_finished(toast))
            
    def _on_fade_out_finished(self, toast):
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
        toast.close()
        toast.deleteLater()
        self._reposition_toasts()
        
    def _reposition_toasts(self):
        """Stacks toasts from bottom-right."""
        if not self.main_window:
            return
            
        window_rect = self.main_window.geometry()
        x = window_rect.right() - self.margin
        current_y = window_rect.bottom() - self.margin
        
        for toast in reversed(self.active_toasts):
            toast_size = toast.sizeHint()
            # If sizeHint is wrong (widget not shown yet properly), we might need a default
            w = max(200, toast_size.width())
            h = toast_size.height()
            
            toast.setFixedSize(w, h)
            toast.move(x - w, current_y - h)
            current_y -= (h + self.spacing)
