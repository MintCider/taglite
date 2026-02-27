"""Reusable tag chip widget with QPainter-drawn rounded background.

Uses QPainter + Antialiasing for smooth rounded corners (no QSS bezier artifacts).
Hover overlay and × are painted in paintEvent (no QPushButton overlay), ensuring
perfect alignment with the chip's rounded shape.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


def _parse_color(hex_color: str | None) -> QColor:
    if hex_color and len(hex_color.lstrip("#")) == 6:
        return QColor(hex_color)
    return QColor("#0078d4")


class TagChipFrame(QFrame):
    """A tag chip with QPainter-drawn rounded background.

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
        self._color = _parse_color(color)
        self._dimmed = dimmed
        self._clickable = clickable
        self._removable = removable
        self._hovered = False

        # Transparent background — we paint it ourselves
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")

        # Layout: only the label (centered)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(0)

        if dimmed:
            label_style = "color: rgba(128,128,128,0.5); font-size: 12px; background: transparent;"
        else:
            label_style = f"color: {color or '#0078d4'}; font-size: 12px; background: transparent;"

        self._label = QLabel(text)
        self._label.setStyleSheet(label_style)
        self._label.setAlignment(Qt.AlignVCenter)
        lay.addWidget(self._label, alignment=Qt.AlignCenter)

        if clickable or removable:
            self.setCursor(Qt.PointingHandCursor)

    # ---- QPainter background + overlay ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 1) Draw chip background
        if self._dimmed:
            bg = QColor(128, 128, 128, 20)
            border = QColor(128, 128, 128, 51)
        else:
            r, g, b = self._color.red(), self._color.green(), self._color.blue()
            bg = QColor(r, g, b, 25)
            border = QColor(r, g, b, 76)

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 12, 12)

        # 2) Hover overlay + × (only when removable)
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


class AddTagButton(QPushButton):
    """A '+ 添加标签' button with QPainter-drawn rounded background.

    Matches the visual style of TagChipFrame (no QSS border-radius artifacts).
    """

    def __init__(self, text: str = "+ 添加标签", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
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
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()

    def sizeHint(self):
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.text()) + 24
        h = fm.height() + 8
        from PySide6.QtCore import QSize
        return QSize(w, h)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)
