"""
Qt Video Player for StreamCapEvo.

Plays recorded videos and live stream previews using QtMultimedia.
"""

import os
from PySide6.QtCore import Qt, QUrl, QTime
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from app.utils.logger import logger
from app.utils.i18n import tr
from app.qt.utils.typography import body_font


class QtVideoPlayer(QDialog):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.setWindowTitle("Video Player")
        self.resize(1000, 650)
        self.setMinimumSize(800, 500)
        
        # Set default font to avoid setPointSize <= 0 warning
        self.setFont(body_font(10))
        
        self._setup_ui()
        self._setup_player()
        
        self._is_playing = False
        self._duration = 0

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setObjectName("videoPlayer")

        # 1. Video Render Widget
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: black;")
        container_layout = QVBoxLayout(self.video_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        container_layout.addWidget(self.video_widget)
        self.layout.addWidget(self.video_container)
        
        # 2. Controls Area
        self.controls_widget = QWidget()
        self.controls_widget.setFixedHeight(100)
        self.controls_widget.setObjectName("playerControls")
        self.controls_widget.setStyleSheet("""
            #playerControls { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #252525, stop:1 #1a1a1a);
                border-top: 1px solid #333;
            }
            QPushButton { border-radius: 4px; padding: 6px 12px; }
            QLabel { color: #eee; font-family: 'Consolas', monospace; }
        """)
        
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(20, 10, 20, 15)
        
        # Seek bar
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setFixedHeight(20)
        self.seek_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        controls_layout.addWidget(self.seek_slider)
        
        # Buttons row
        btns_row = QHBoxLayout()
        btns_row.setSpacing(15)
        
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFixedWidth(100)
        self.play_btn.setProperty("class", "primary-btn")
        self.play_btn.clicked.connect(self._toggle_playback)
        btns_row.addWidget(self.play_btn)
        
        self.time_label = QLabel("00:00 / 00:00")
        btns_row.addWidget(self.time_label)
        
        btns_row.addStretch()
        
        # Action buttons (Copy, Open Room)
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(8)
        btns_row.addLayout(self.actions_layout)
        
        self.fullscreen_btn = QPushButton("📺 Fullscreen")
        self.fullscreen_btn.setProperty("class", "secondary")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        btns_row.addWidget(self.fullscreen_btn)
        
        self.close_btn = QPushButton("✕ Close")
        self.close_btn.setProperty("class", "danger")
        self.close_btn.clicked.connect(self.close)
        btns_row.addWidget(self.close_btn)
        
        controls_layout.addLayout(btns_row)
        self.layout.addWidget(self.controls_widget)
        
        # Double click on video to toggle fullscreen
        self.video_widget.mouseDoubleClickEvent = self._on_video_double_click

    def _setup_player(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_error)

    def _on_video_double_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_fullscreen()

    def keyPressEvent(self, event):
        """Keyboard shortcuts for the player (Space, F, Esc, M)."""
        key = event.key()
        if key == Qt.Key.Key_Space:
            self._toggle_playback()
        elif key == Qt.Key.Key_F:
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_M:
            self._toggle_mute()
        elif key == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.close()
        elif key == Qt.Key.Key_Left:
            self.player.setPosition(max(0, self.player.position() - 10000)) # -10s
        elif key == Qt.Key.Key_Right:
            self.player.setPosition(min(self._duration, self.player.position() + 10000)) # +10s
        else:
            super().keyPressEvent(event)

    def _toggle_fullscreen(self):
        """Toggle between windowed and fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_mute(self):
        is_muted = self.audio_output.isMuted()
        self.audio_output.setMuted(not is_muted)
        if hasattr(self.app.main_window, "show_toast"):
            msg = tr("toast.muted", default="Muted") if not is_muted else tr("toast.unmuted", default="Unmuted")
            self.app.main_window.show_toast(msg, "info", 1000)

    async def preview_video(self, source, is_file_path=True, room_url=None):
        """Prepare and show the video."""
        self.stop()
        
        # Update title
        filename = os.path.basename(source) if is_file_path else "Live Stream"
        self.setWindowTitle(f"Playing: {filename}")
        
        # Update action buttons
        self._update_actions(source, room_url)
        
        if is_file_path:
            file_url = QUrl.fromLocalFile(source)
            self.player.setSource(file_url)
        else:
            self.player.setSource(QUrl(source))
            
        self.show()
        self.player.play()

    def _update_actions(self, source, room_url):
        # Clear previous actions
        for i in reversed(range(self.actions_layout.count())): 
            self.actions_layout.itemAt(i).widget().setParent(None)
            
        if room_url:
            btn = QPushButton("🌐 Open Room")
            btn.clicked.connect(lambda: self.app.page.launch_url(room_url)) # Flet compat? 
            # In QtMainWindow we might need another way to launch URL
            def open_room():
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(room_url))
            btn.clicked.disconnect()
            btn.clicked.connect(open_room)
            self.actions_layout.addWidget(btn)
            
        copy_btn = QPushButton("📋 Copy Source")
        def copy_to_clip():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(source)
        copy_btn.clicked.connect(copy_to_clip)
        self.actions_layout.addWidget(copy_btn)

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸ Pause")
        else:
            self.play_btn.setText("▶ Play")

    def _on_position_changed(self, position):
        self.seek_slider.setValue(position)
        self._update_time_label(position, self._duration)

    def _on_duration_changed(self, duration):
        self._duration = duration
        self.seek_slider.setRange(0, duration)
        self._update_time_label(self.player.position(), duration)

    def _on_seek_moved(self, position):
        self.player.setPosition(position)

    def _update_time_label(self, current, total):
        curr_time = QTime(0, 0).addMSecs(current).toString("mm:ss")
        total_time = QTime(0, 0).addMSecs(total).toString("mm:ss")
        self.time_label.setText(f"{curr_time} / {total_time}")

    def _on_error(self, error, error_string):
        logger.error(f"Video Player Error: {error_string}")

    def stop(self):
        self.player.stop()
        self.player.setSource(QUrl())

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
