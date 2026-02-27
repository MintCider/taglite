"""Tag color picker — a grid of preset swatches + custom color option."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget

from taglite.ui.flow_layout import FlowLayout

# 12 preset colors
PRESET_COLORS = [
    "#e74c3c",  # red
    "#e67e22",  # orange
    "#f39c12",  # amber
    "#2ecc71",  # green
    "#1abc9c",  # teal
    "#3498db",  # blue
    "#0078d4",  # accent blue
    "#9b59b6",  # purple
    "#e84393",  # pink
    "#636e72",  # grey
    "#6c5ce7",  # indigo
    "#00b894",  # mint
]

SWATCH_SIZE = 24


class _SwatchButton(QPushButton):
    """A single color swatch with QPainter-drawn selection ring."""

    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._selected = False
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())

        if self._selected:
            hl = self.palette().highlight().color()
            painter.setPen(QPen(hl, 2.5))
            painter.setBrush(QBrush(QColor(self._color)))
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 4, 4)
        else:
            painter.setPen(QPen(QColor(128, 128, 128, 64), 1))
            painter.setBrush(QBrush(QColor(self._color)))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

        painter.end()


class _CustomSwatchButton(QPushButton):
    """Custom color button: shows '...' when empty, filled + highlight ring when a color is set."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._color: str | None = None
        self._selected = False
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("自定义颜色\u2026")
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._selected = True
        self.update()

    def clear_color(self) -> None:
        self._color = None
        self._selected = False
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())

        if self._color and self._selected:
            hl = self.palette().highlight().color()
            painter.setPen(QPen(hl, 2.5))
            painter.setBrush(QBrush(QColor(self._color)))
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 4, 4)
        else:
            # Default: dashed border + "..." text
            pen = QPen(QColor(128, 128, 128, 102), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

            painter.setPen(QColor(128, 128, 128, 160))
            font = painter.font()
            font.setPixelSize(11)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "\u2026")

        painter.end()


class ColorPicker(QWidget):
    """Color swatch grid for tag color selection. Emits color_selected(hex_str)."""

    color_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current: str | None = None
        self._swatches: list[_SwatchButton] = []

        layout = FlowLayout(self, h_spacing=4, v_spacing=4)
        layout.setContentsMargins(0, 4, 0, 4)

        for color in PRESET_COLORS:
            btn = _SwatchButton(color)
            btn.clicked.connect(lambda checked=False, c=color: self._pick(c))
            layout.addWidget(btn)
            self._swatches.append(btn)

        # Custom color button
        self._custom_btn = _CustomSwatchButton()
        self._custom_btn.clicked.connect(self._pick_custom)
        layout.addWidget(self._custom_btn)

    @property
    def current_color(self) -> str | None:
        return self._current

    def _pick(self, color: str) -> None:
        self._current = color
        for s in self._swatches:
            s.set_selected(s._color == color)
        self._custom_btn.clear_color()
        self.color_selected.emit(color)

    def _pick_custom(self) -> None:
        initial = QColor(self._current) if self._current else QColor("#0078d4")
        color = QColorDialog.getColor(initial, self, "选择标签颜色")
        if color.isValid():
            hex_color = color.name()
            self._current = hex_color
            for s in self._swatches:
                s.set_selected(False)
            self._custom_btn.set_color(hex_color)
            self.color_selected.emit(hex_color)
