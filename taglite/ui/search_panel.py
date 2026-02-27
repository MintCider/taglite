"""Advanced search panel: tag chips, extension, size range, date range."""

from PySide6.QtCore import QDate, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from taglite.core.tagger import list_all_tags
from taglite.db.models import Tag
from taglite.ui.flow_layout import FlowLayout
from taglite.ui.tag_chip import TagChipFrame


def _tag_display(tag: Tag) -> str:
    if tag.key:
        return f"{tag.key}={tag.value}"
    return tag.value


def _tag_search_token(tag: Tag) -> str:
    if tag.key:
        return f"tag:{tag.key}={tag.value}"
    return f"tag:{tag.value}"


class PainterButton(QWidget):
    """A compact button drawn with QPainter — no QSS border-radius artifacts."""

    clicked = Signal()

    def __init__(self, text: str, *, primary: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._primary = primary
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(24)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self._primary:
            hl = self.palette().highlight().color()
            bg = QColor(hl.red(), hl.green(), hl.blue(), 220 if self._hovered else 200)
            border = hl
            text_color = self.palette().highlightedText().color()
        elif self._hovered:
            bg = QColor(128, 128, 128, 25)
            border = QColor(128, 128, 128, 80)
            text_color = self.palette().windowText().color()
        else:
            bg = QColor(128, 128, 128, 12)
            border = QColor(128, 128, 128, 50)
            text_color = self.palette().windowText().color()

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 4, 4)

        painter.setPen(text_color)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._text)
        painter.end()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self._text) + 20
        return QSize(w, 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()


class AdvancedSearchPanel(QWidget):
    """Expandable advanced search panel that writes filters back to a search bar."""

    search_requested = Signal(str)  # emits assembled search text

    def __init__(self, db_uri: str, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self.setObjectName("advancedSearchPanel")
        # Don't stretch vertically — only take as much height as content needs
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._build_ui()
        self.setVisible(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 4)
        layout.setSpacing(2)

        # --- Tag label ---
        tag_label = QLabel("标签")
        tag_label.setStyleSheet("font-size: 11px; color: palette(placeholderText); padding: 0;")
        tag_label.setFixedHeight(16)
        layout.addWidget(tag_label)

        # --- Tag chips (dynamic height via FlowLayout) ---
        self._tag_container = QWidget()
        # Tell parent layout to query heightForWidth from our FlowLayout
        sp = self._tag_container.sizePolicy()
        sp.setHeightForWidth(True)
        sp.setVerticalPolicy(QSizePolicy.Preferred)
        self._tag_container.setSizePolicy(sp)
        self._tag_flow = FlowLayout(self._tag_container, h_spacing=4, v_spacing=4)
        self._tag_flow.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tag_container)
        self._tag_chips: dict[int, TagChipFrame] = {}
        self._selected_tags: set[int] = set()

        # --- Filter row: extension + size + date + buttons (all 24px height) ---
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.setContentsMargins(0, 2, 0, 0)

        # Extension
        ext_label = QLabel("扩展名")
        ext_label.setStyleSheet("font-size: 11px; color: palette(placeholderText);")
        self._ext_input = QLineEdit()
        self._ext_input.setPlaceholderText("pdf, docx")
        self._ext_input.setFixedWidth(80)
        self._ext_input.setFixedHeight(24)
        filter_row.addWidget(ext_label)
        filter_row.addWidget(self._ext_input)

        # Size range
        size_label = QLabel("大小")
        size_label.setStyleSheet("font-size: 11px; color: palette(placeholderText);")
        self._size_min = QLineEdit()
        self._size_min.setPlaceholderText("最小")
        self._size_min.setFixedWidth(60)
        self._size_min.setFixedHeight(24)
        size_dash = QLabel("–")
        self._size_max = QLineEdit()
        self._size_max.setPlaceholderText("最大")
        self._size_max.setFixedWidth(60)
        self._size_max.setFixedHeight(24)
        filter_row.addWidget(size_label)
        filter_row.addWidget(self._size_min)
        filter_row.addWidget(size_dash)
        filter_row.addWidget(self._size_max)

        # Date range
        self._date_after_cb = QCheckBox("起始")
        self._date_after_cb.setStyleSheet("font-size: 11px;")
        self._date_after_cb.toggled.connect(self._toggle_date_after)
        self._date_after = QDateEdit()
        self._date_after.setCalendarPopup(True)
        self._date_after.setFixedWidth(100)
        self._date_after.setFixedHeight(24)
        self._date_after.setDisplayFormat("yyyy-MM-dd")
        self._date_after.setEnabled(False)

        self._date_before_cb = QCheckBox("结束")
        self._date_before_cb.setStyleSheet("font-size: 11px;")
        self._date_before_cb.toggled.connect(self._toggle_date_before)
        self._date_before = QDateEdit()
        self._date_before.setCalendarPopup(True)
        self._date_before.setFixedWidth(100)
        self._date_before.setFixedHeight(24)
        self._date_before.setDisplayFormat("yyyy-MM-dd")
        self._date_before.setEnabled(False)

        # Set minimum dates and use special value text for "empty" state
        min_date = QDate(2000, 1, 1)
        self._date_after.setMinimumDate(min_date)
        self._date_after.setDate(min_date)
        self._date_after.setSpecialValueText(" ")
        self._date_before.setMinimumDate(min_date)
        self._date_before.setDate(min_date)
        self._date_before.setSpecialValueText(" ")

        filter_row.addWidget(self._date_after_cb)
        filter_row.addWidget(self._date_after)
        filter_row.addWidget(self._date_before_cb)
        filter_row.addWidget(self._date_before)

        # Spacer pushes buttons to the right, but buttons have minimum width
        # so they can't be squeezed out
        filter_row.addWidget(QWidget(), 1)  # flexible spacer

        # Buttons — fixed 24px height, minimum width guaranteed
        self._clear_btn = PainterButton("清除")
        self._clear_btn.clicked.connect(self._clear_all)
        self._apply_btn = PainterButton("搜索", primary=True)
        self._apply_btn.clicked.connect(self._apply)
        filter_row.addWidget(self._clear_btn)
        filter_row.addWidget(self._apply_btn)

        layout.addLayout(filter_row)

    def reload_tags(self, db_uri: str | None = None) -> None:
        """Refresh the tag chips from DB."""
        if db_uri is not None:
            self._db_uri = db_uri

        while self._tag_flow.count():
            item = self._tag_flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._tag_chips.clear()

        tags = list_all_tags(self._db_uri)
        for tag in tags:
            chip = TagChipFrame(
                _tag_display(tag),
                color=tag.color,
                tag_id=tag.id,
                clickable=True,
                removable=False,
            )
            chip.clicked.connect(lambda tid=tag.id: self._toggle_tag(tid))
            self._tag_flow.addWidget(chip)
            self._tag_chips[tag.id] = chip

        # Restore selection state
        for tid in list(self._selected_tags):
            if tid in self._tag_chips:
                self._tag_chips[tid].set_selected(True)
            else:
                self._selected_tags.discard(tid)

    def _toggle_tag(self, tag_id: int) -> None:
        if tag_id in self._selected_tags:
            self._selected_tags.discard(tag_id)
            if tag_id in self._tag_chips:
                self._tag_chips[tag_id].set_selected(False)
        else:
            self._selected_tags.add(tag_id)
            if tag_id in self._tag_chips:
                self._tag_chips[tag_id].set_selected(True)

    def _toggle_date_after(self, checked: bool) -> None:
        self._date_after.setEnabled(checked)
        if checked and self._date_after.date() == self._date_after.minimumDate():
            self._date_after.setDate(QDate.currentDate().addMonths(-1))

    def _toggle_date_before(self, checked: bool) -> None:
        self._date_before.setEnabled(checked)
        if checked and self._date_before.date() == self._date_before.minimumDate():
            self._date_before.setDate(QDate.currentDate())

    def _apply(self) -> None:
        """Build search text from panel state and emit."""
        parts: list[str] = []

        # Tags
        tags = list_all_tags(self._db_uri)
        tag_map = {t.id: t for t in tags}
        for tid in self._selected_tags:
            if tid in tag_map:
                parts.append(_tag_search_token(tag_map[tid]))

        # Extension
        ext = self._ext_input.text().strip()
        if ext:
            for e in ext.replace(",", " ").split():
                e = e.strip().lstrip(".")
                if e:
                    parts.append(f"ext:{e}")

        # Size
        smin = self._size_min.text().strip()
        if smin:
            parts.append(f"size>{smin}")
        smax = self._size_max.text().strip()
        if smax:
            parts.append(f"size<{smax}")

        # Dates
        if self._date_after_cb.isChecked():
            parts.append(f"after:{self._date_after.date().toString('yyyy-MM-dd')}")
        if self._date_before_cb.isChecked():
            parts.append(f"before:{self._date_before.date().toString('yyyy-MM-dd')}")

        search_text = " ".join(parts)
        self.search_requested.emit(search_text)

    def _clear_all(self) -> None:
        """Reset all filters."""
        self._selected_tags.clear()
        for chip in self._tag_chips.values():
            chip.set_selected(False)
        self._ext_input.clear()
        self._size_min.clear()
        self._size_max.clear()
        self._date_after_cb.setChecked(False)
        self._date_before_cb.setChecked(False)
        min_date = QDate(2000, 1, 1)
        self._date_after.setDate(min_date)
        self._date_before.setDate(min_date)
        self.search_requested.emit("")
