"""Reusable tag chip widget with QPainter-drawn rounded background.

Uses QPainter + Antialiasing for smooth rounded corners (no QSS bezier artifacts).
Everything (background, text, hover overlay, ×) is painted in paintEvent for correct
z-order — no child QLabel that could render on top of the overlay.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget


def _parse_color(hex_color: str | None) -> QColor:
    if hex_color and len(hex_color.lstrip("#")) == 6:
        return QColor(hex_color)
    return QColor("#0078d4")


class TagChipFrame(QFrame):
    """A tag chip with QPainter-drawn background, text, and overlay.

    Signals:
        clicked()          — left-click on the chip (only if clickable=True)
        remove_requested() — click on chip when hovered (only if removable=True)
        edit_requested()   — right-click context menu
    """

    clicked = Signal()
    remove_requested = Signal()
    edit_requested = Signal()

    def __init__(
        self,
        text: str,
        color: str | None = None,
        *,
        tag_id: int | None = None,
        dimmed: bool = False,
        removable: bool = False,
        clickable: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.tag_id = tag_id
        self._text = text
        self._color = _parse_color(color)
        self._color_hex = color
        self._dimmed = dimmed
        self._clickable = clickable
        self._removable = removable
        self._hovered = False
        self._selected = False

        # Transparent background — we paint everything ourselves
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")

        if clickable or removable:
            self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self._text) + 18  # 9px padding each side
        h = fm.height() + 8
        return QSize(max(w, 24), max(h, 22))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ---- QPainter — all rendering ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 1) Chip background
        if self._dimmed:
            bg = QColor(128, 128, 128, 20)
            border = QColor(128, 128, 128, 51)
            text_color = QColor(128, 128, 128, 128)
        else:
            r, g, b = self._color.red(), self._color.green(), self._color.blue()
            bg = QColor(r, g, b, 25)
            border = QColor(r, g, b, 76)
            text_color = QColor(self._color_hex or "#0078d4")

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 12, 12)

        # 2) Selected highlight ring (theme color)
        if self._selected:
            hl = self.palette().highlight().color()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(hl, 2.5))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        # 3) Hover overlay + × (only when removable)
        if self._hovered and self._removable:
            # Semi-transparent overlay matching chip shape exactly
            painter.setBrush(QColor(0, 0, 0, 38))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 12, 12)

            # Draw red × with fixed size, centered
            CROSS_ARM = 5  # half-length of each line
            cx = rect.center().x()
            cy = rect.center().y()
            pen = QPen(QColor("#c42b1c"), 2.5, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(cx - CROSS_ARM, cy - CROSS_ARM),
                QPointF(cx + CROSS_ARM, cy + CROSS_ARM),
            )
            painter.drawLine(
                QPointF(cx + CROSS_ARM, cy - CROSS_ARM),
                QPointF(cx - CROSS_ARM, cy + CROSS_ARM),
            )
        else:
            # 4) Draw text (only when not showing ×)
            font = painter.font()
            font.setPixelSize(12)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignCenter, self._text)

        painter.end()

    # ---- Mouse events ----

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._removable and self._hovered:
                self.remove_requested.emit()
            elif self._clickable:
                self.clicked.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.edit_requested.emit()

    # ---- Hover tracking ----

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)


class AddTagButton(QWidget):
    """A '+ 添加标签' button with QPainter-drawn rounded background.

    Matches the visual style of TagChipFrame (no QSS border-radius artifacts).
    """

    clicked = Signal()

    def __init__(self, text: str = "+ 添加标签", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self._hovered:
            bg = QColor(0, 120, 212, 15)
            border_color = QColor("#0078d4")
            text_color = QColor("#0078d4")
        else:
            bg = QColor(128, 128, 128, 15)
            border_color = QColor(128, 128, 128, 51)
            text_color = QColor(128, 128, 128, 160)

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect, 12, 12)

        # Draw text centered
        painter.setPen(text_color)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._text)
        painter.end()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self._text) + 24
        h = fm.height() + 8
        return QSize(w, h)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)
