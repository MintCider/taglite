"""QApplication startup, dark mode detection, QSS loading, font setup."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWidgets import QApplication


def _is_dark_mode() -> bool:
    """Detect system dark mode preference (Windows)."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except Exception:
            return False
    return False


def _apply_dark_palette(app: QApplication) -> None:
    """Apply a dark color palette to the application."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(32, 32, 32))
    palette.setColor(QPalette.WindowText, QColor(230, 230, 230))
    palette.setColor(QPalette.Base, QColor(40, 40, 40))
    palette.setColor(QPalette.AlternateBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ToolTipBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ToolTipText, QColor(230, 230, 230))
    palette.setColor(QPalette.Text, QColor(230, 230, 230))
    palette.setColor(QPalette.Button, QColor(50, 50, 50))
    palette.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.Link, QColor(56, 163, 255))
    palette.setColor(QPalette.Highlight, QColor(0, 120, 212))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Dark, QColor(160, 160, 160))
    palette.setColor(QPalette.PlaceholderText, QColor(140, 140, 140))
    app.setPalette(palette)


def _load_qss() -> str:
    """Load the theme QSS file."""
    qss_path = Path(__file__).resolve().parent.parent.parent / "resources" / "theme.qss"
    if qss_path.exists():
        return qss_path.read_text("utf-8")
    return ""


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create and configure the QApplication."""
    if argv is None:
        argv = sys.argv
    app = QApplication(argv)

    # Font
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
    elif sys.platform == "darwin":
        app.setFont(QFont(".AppleSystemUIFont", 13))

    # Dark mode
    if _is_dark_mode():
        _apply_dark_palette(app)

    # QSS
    app.setStyleSheet(_load_qss())

    return app
