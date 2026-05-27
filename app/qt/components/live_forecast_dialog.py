"""
Qt Manual Live Forecast Dialog — StreamCapEvo.
Displays on-demand forecast of upcoming live streams.
"""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QScrollArea, QWidget, QFrame, QSizePolicy
)
from PySide6.QtGui import QColor
from app.utils.i18n import tr

from app.core.recording.precog import Precog
from app.qt.themes.theme import theme_manager
from datetime import datetime

# Platform colors for badges
_PLATFORM_COLORS = {
    "chaturbate": "#FF9800",
    "chaturbate-privates": "#F44336",
    "tiktok": "#000000",
    "default": "#4CAF50"
}

def _get_platform_color(platform: str | None) -> str:
    if not platform:
        return _PLATFORM_COLORS["default"]
    p_lower = platform.lower()
    return _PLATFORM_COLORS.get(p_lower, _PLATFORM_COLORS["default"])

def _get_forecast_time_info(recording) -> dict:
    """
    Return dict with state, text_key, text, color, prefix for the forecast time column.

    Delegado a ``Precog.time_state`` para mantener la lógica centralizada.
    """
    return Precog.time_state(recording)


def _get_confidence_color(confidence: str, colors: dict) -> str:
    if confidence == "high":
        return "#43A047"
    if confidence == "medium":
        return "#FB8C00"
    return colors["text_muted"]

class ForecastItemWidget(QFrame):
    """Single streamer forecast item with a clean UI."""
    def __init__(self, recording, likelihood: float, parent=None):
        super().__init__(parent)
        self.recording = recording
        self._likelihood = likelihood
        
        self.setMinimumHeight(78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        # Style the frame
        c = theme_manager.colors
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 6px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        layout.setSpacing(12)
        
        # Platform badge
        platform = self.recording.platform or "Unknown"
        p_lower = platform.lower()
        if p_lower == "chaturbate":
            p_text = "CB"
        elif p_lower == "chaturbate-privates":
            p_text = "CBP"
        elif p_lower == "tiktok":
            p_text = "TK"
        else:
            p_text = platform[:2].upper()
            
        platform_color = _get_platform_color(platform)
        platform_badge = QLabel(p_text)
        platform_badge.setStyleSheet(f"""
            font-size: 11px;
            font-weight: bold;
            color: white;
            background-color: {platform_color};
            border-radius: 4px;
            padding: 3px 6px;
            border: none;
        """)
        platform_badge.setFixedWidth(30)
        platform_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(platform_badge)
        
        # Streamer name
        name_lbl = QLabel(self.recording.streamer_name)
        name_lbl.setStyleSheet(f"""
            font-size: 13px; 
            font-weight: 600;
            color: {c['text']}; 
            border: none;
            background: transparent;
        """)
        top_row.addWidget(name_lbl, 1)
        
        # Consistency bar (10 segments)
        consistency = self.recording.consistency_score or 0.0
        filled = int(consistency * 10)
        bar_str = "●" * filled + "○" * (10 - filled)
        consistency_lbl = QLabel(bar_str)
        consistency_lbl.setStyleSheet(f"""
            font-size: 11px; 
            color: {c['text_muted']}; 
            border: none;
            background: transparent;
        """)
        consistency_lbl.setFixedWidth(80)
        consistency_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(consistency_lbl)
        
        # Likelihood percentage
        likelihood_pct = int(self._likelihood * 100)
        lik_color = "#4CAF50" if self._likelihood >= 0.6 else "#FF9800" if self._likelihood >= 0.3 else c['text_muted']
        
        lik_lbl = QLabel(f"{likelihood_pct}%")
        lik_lbl.setStyleSheet(f"""
            font-size: 12px; 
            font-weight: bold;
            color: {lik_color}; 
            border: none;
            background: transparent;
        """)
        lik_lbl.setFixedWidth(45)
        lik_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(lik_lbl)

        # Time / Status
        self.time_lbl = QLabel()
        self.time_lbl.setFixedWidth(120)
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.time_lbl)

        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        self.reason_lbl = QLabel()
        self.reason_lbl.setStyleSheet(f"""
            font-size: 11px;
            color: {c['text_muted']};
            border: none;
            background: transparent;
        """)
        bottom_row.addWidget(self.reason_lbl, 1)

        self.window_lbl = QLabel()
        self.window_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self.window_lbl)
        layout.addLayout(bottom_row)
        
        self.update_time_info()

    def update_time_info(self):
        c = theme_manager.colors
        info = _get_forecast_time_info(self.recording)
        forecast = Precog.predict(self.recording).forecast_details
        
        if info["state"] == "none":
            self.time_lbl.setText("")
            return
            
        if "text_key" in info:
            translated_text = tr(info["text_key"])
            if "args" in info:
                translated_text = translated_text.format(**info["args"])
            text = f"{info.get('prefix', '')}{translated_text} {info.get('text', '')}"
        else:
            text = info.get("text", "")
            
        color = info.get("color") if info.get("color") else c['text_muted']
        
        self.time_lbl.setText(text)
        self.time_lbl.setStyleSheet(f"""
            font-size: 11px; 
            font-weight: {'bold' if info["state"] in ('expected', 'delayed', 'countdown', 'live_range') else 'normal'};
            color: {color}; 
            border: none;
            background: transparent;
        """)

        confidence_text = tr(f"live_forecast_dialog.confidence_{forecast['confidence']}")
        reason_text = tr(forecast["reason_key"])
        avg_delay = forecast.get("avg_delay_minutes")
        if avg_delay is not None:
            reason_text = (
                f"{reason_text} · "
                f"{tr('live_forecast_dialog.avg_delay_label').format(minutes=avg_delay)}"
            )
        self.reason_lbl.setText(f"{confidence_text} · {reason_text}")
        self.reason_lbl.setStyleSheet(f"""
            font-size: 11px;
            color: {_get_confidence_color(forecast['confidence'], c)};
            border: none;
            background: transparent;
        """)

        next_slot = forecast.get("next_slot_text") or "—"
        window_text = forecast.get("window_text") or "—"
        self.window_lbl.setText(
            tr("live_forecast_dialog.window_label").format(next=next_slot, window=window_text)
        )
        self.window_lbl.setStyleSheet(f"""
            font-size: 11px;
            color: {c['text_muted']};
            border: none;
            background: transparent;
        """)

        horizons = forecast.get("horizons") or {}
        if horizons:
            horizon_text = " · ".join(
                f"{minutes}m {int(probability * 100)}%"
                for minutes, probability in horizons.items()
            )
            self.window_lbl.setToolTip(
                tr("live_forecast_dialog.horizons_tooltip").format(horizons=horizon_text)
            )


class LiveForecastDialog(QDialog):
    def __init__(self, app_context, recordings, parent=None):
        super().__init__(parent)
        
        # Requirement: Proper memory management
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        self.app = app_context
        self.recordings = recordings
        
        self.app.event_bus.subscribe("language_changed", self._on_language_changed)
        
        self.setWindowTitle(tr("live_forecast_dialog.title"))
        self.setMinimumSize(780, 450)
        self.resize(840, 500)
        
        self._setup_ui()

    def _on_language_changed(self, topic, new_language):
        self._retranslate_ui()

    def closeEvent(self, event):
        self.app.event_bus.unsubscribe("language_changed", self._on_language_changed)
        super().closeEvent(event)

    def _retranslate_ui(self):
        self.setWindowTitle(tr("live_forecast_dialog.title"))
        # Header
        self.title_lbl.setText(tr("live_forecast_dialog.title"))
        self.subtitle_lbl.setText(tr("live_forecast_dialog.subtitle"))
        # Footer
        self.close_btn.setText(tr("live_forecast_dialog.close"))
        
        # Re-populate list to update item text
        self._populate_list()

    def _setup_ui(self):
        c = theme_manager.colors
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c['bg']};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        
        self.title_lbl = QLabel(tr("live_forecast_dialog.title"))
        self.title_lbl.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {c['text']};")
        header_layout.addWidget(self.title_lbl)
        
        self.subtitle_lbl = QLabel(tr("live_forecast_dialog.subtitle"))
        self.subtitle_lbl.setStyleSheet(f"font-size: 12px; color: {c['text_muted']};")
        header_layout.addWidget(self.subtitle_lbl)
        
        layout.addLayout(header_layout)
        
        # Scroll Area for the list
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: {c['surface']};
                width: 12px;
                border-radius: 5px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {c['border']};
                border-radius: 5px;
                margin: 1px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {c['text_muted']};
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: {c['surface']};
                border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 8, 0)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)
        
        # Populate
        self._populate_list()
        
        # Footer
        btns = QHBoxLayout()
        btns.addStretch()
        
        self.close_btn = QPushButton(tr("live_forecast_dialog.close"))
        self.close_btn.setProperty("class", "primary") # Use app theme primary class
        self.close_btn.setMinimumWidth(100)
        self.close_btn.setFixedHeight(36)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        btns.addWidget(self.close_btn)
        
        layout.addLayout(btns)
        
    def _populate_list(self):
        # Clear existing items
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        c = theme_manager.colors
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

        def _slot_minutes_until(rec) -> int | None:
            """Return minutes until the next predicted slot, or None if unknown.

            For live / active-window states returns 0 so they sort first.
            For future slots returns the actual minutes-until (capped at 300 for
            the filter, but the raw value is used for sorting).
            """
            info = _get_forecast_time_info(rec)
            state = info.get("state")
            # Imminent / overdue — sort first regardless of wall-clock distance
            if state in ('live_range', 'expected', 'delayed') or rec.is_live:
                return 0
            # Future slots — parse next_slot_text for real distance
            forecast = Precog.predict(rec).forecast_details
            slot = forecast.get("next_slot_text", "")
            if not slot:
                return None
            try:
                parts = slot.strip().split(":")
                slot_min = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
            except (ValueError, IndexError):
                return None
            if slot_min >= current_minutes:
                return slot_min - current_minutes
            return (1440 - current_minutes) + slot_min

        # Gather forecasts with proximity info
        forecasts = []
        for rec in self.recordings:
            score = Precog.predict(rec).likelihood
            info = _get_forecast_time_info(rec)
            state = info.get("state")

            # Only include if within 5 hours or live/imminent
            if rec.is_live or state in ('live_range', 'expected', 'delayed', 'countdown'):
                forecasts.append((rec, score, _slot_minutes_until(rec)))
                continue

            if state in ('upcoming',) or score >= 0.35:
                mins = _slot_minutes_until(rec)
                if mins is not None and mins <= 300:
                    forecasts.append((rec, score, mins))

        # Sort by proximity (closest first), then score as tiebreaker
        forecasts.sort(key=lambda x: (x[2], -x[1]))
        
        if not forecasts:
            empty_lbl = QLabel(tr("live_forecast_dialog.no_forecast"))
            empty_lbl.setStyleSheet(f"font-size: 13px; color: {c['text_muted']}; font-style: italic;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll_layout.addWidget(empty_lbl)
            return
        
        for rec, score, _mins in forecasts:
            item_widget = ForecastItemWidget(rec, score, parent=self.scroll_content)
            self.scroll_layout.addWidget(item_widget)

