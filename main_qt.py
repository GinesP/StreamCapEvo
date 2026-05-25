"""
StreamCapEvo – Qt entry point.

Run this script to launch the Qt-based UI prototype.
The Flet version remains available via main.py.

Usage:
    python main_qt.py
"""

import sys
import os
import asyncio
import signal
import ctypes
from qasync import QEventLoop
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QLoggingCategory
from PySide6.QtGui import QFont, QIcon

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.qt_app_manager import QtApp
from app.qt.main_window import MainWindow
from app.qt.utils.typography import BODY_FONT_FAMILY, body_font, load_app_fonts

_qt_app = None

async def start_app():
    """Asynchronously initialize core and launch the main window."""
    global _qt_app
    # Initialize Core Application Logic (Sync part happens in __init__)
    _qt_app = QtApp()
    
    # Create and show window immediately for better perceived performance
    window = MainWindow(_qt_app)
    _qt_app.main_window = window
    global _main_window 
    _main_window = window
    window.show()

    # Perform background initialization (update checks, env checks) after window is shown
    await _qt_app.initialize()
    await _qt_app.start_periodic_tasks()

def main():
    """Main entry point."""
    # Silence specific Qt warnings
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts.warning=false;qt.qpa.fonts=false"
    QLoggingCategory.setFilterRules("qt.qpa.fonts.warning=false")

    # Set AppUserModelID for Windows so the taskbar icon displays correctly
    if sys.platform == "win32":
        myappid = 'StreamCapEvo.streamcapevo.app.1'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    # Create the Qt Application
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("StreamCapEvo")
    app.setApplicationDisplayName("StreamCapEvo")
    load_app_fonts()

    # Set the application icon globally. Prefer the multi-resolution ICO on Windows
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_candidates = [
        os.path.join(base_dir, "assets", "icon.ico"),
        os.path.join(base_dir, "assets", "icons", "icon.iconset", "icon_512x512.png"),
    ]
    for icon_path in icon_candidates:
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    # Set a robust default font
    default_font = body_font(10)
    if not default_font.exactMatch():
        default_font = QFont(BODY_FONT_FAMILY, 10)
    if not default_font.exactMatch():
        default_font = QFont("Arial", 10)
    app.setFont(default_font)
    
    # Create and set the qasync event loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Run the application
    with loop:
        # Handle Ctrl+C gracefully
        def sigint_handler(*args):
            print("\nInterrupt received, exiting...")
            app.quit()
        
        signal.signal(signal.SIGINT, sigint_handler)
        
        # Periodic timer dummy to allow Python signal handling on Windows
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(500)

        asyncio.ensure_future(start_app())
        
        try:
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Cleanly stop everything
            if _qt_app:
                # We need to run cleanup in the loop before it closes
                loop.run_until_complete(_qt_app.cleanup())
            
            loop.stop()
            app.quit()
    
    print("Application closed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
