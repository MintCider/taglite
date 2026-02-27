"""Left-bottom panel: tag browser showing all tags in the current backend."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taglite.core.tagger import delete_tag, list_all_tags
from taglite.db.models import Tag
from taglite.ui.flow_layout import FlowLayout
from taglite.ui.tag_chip import TagChipFrame


def _tag_display(tag: Tag) -> str:
    if tag.key:
        return f"{tag.key}={tag.value}"
    return tag.value


class TagBrowser(QWidget):
    """Panel listing all tags. Click to highlight; right-click to delete."""

    tag_deleted = Signal(int)  # tag_id
    tag_selected = Signal(str)  # search text, e.g. "tag:重要" or "tag:key=value"
    tag_deselected = Signal()

    def __init__(self, db_uri: str, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self._selected_tag_id: int | None = None
        self._chips: dict[int, TagChipFrame] = {}
        self._tag_search_text: dict[int, str] = {}  # tag_id → "tag:xxx" search text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("  标签")
        header.setStyleSheet("font-size: 13px; font-weight: 700; padding: 4px 0px;")
        header.setFixedHeight(28)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._content = QWidget()
        self._flow = FlowLayout(self._content, h_spacing=6, v_spacing=6)
        self._flow.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(self._content)
        layout.addWidget(scroll)

    def reload(self, db_uri: str | None = None) -> None:
        """Rebuild the tag list from the database."""
        if db_uri is not None:
            self._db_uri = db_uri

        tags = list_all_tags(self._db_uri)

        # Clear existing chips
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._chips.clear()
        self._tag_search_text.clear()

        for tag in tags:
            chip = TagChipFrame(
                _tag_display(tag),
                color=tag.color,
                tag_id=tag.id,
                clickable=True,
                removable=False,
            )
            chip.clicked.connect(lambda tid=tag.id: self._on_tag_clicked(tid))
            chip.edit_requested.connect(lambda tid=tag.id: self._on_context_menu(tid))
            self._flow.addWidget(chip)
            self._chips[tag.id] = chip
            # Build search text
            if tag.key:
                self._tag_search_text[tag.id] = f"tag:{tag.key}={tag.value}"
            else:
                self._tag_search_text[tag.id] = f"tag:{tag.value}"

        # Restore selection visual if tag still exists
        if self._selected_tag_id in self._chips:
            self._chips[self._selected_tag_id].set_selected(True)
        else:
            self._selected_tag_id = None

    def clear_selection(self) -> None:
        """Clear the current tag selection without emitting signals."""
        if self._selected_tag_id in self._chips:
            self._chips[self._selected_tag_id].set_selected(False)
        self._selected_tag_id = None

    def _on_tag_clicked(self, tag_id: int) -> None:
        if self._selected_tag_id == tag_id:
            # Deselect
            self._chips[tag_id].set_selected(False)
            self._selected_tag_id = None
            self.tag_deselected.emit()
        else:
            # Deselect previous
            if self._selected_tag_id in self._chips:
                self._chips[self._selected_tag_id].set_selected(False)
            # Select new
            self._selected_tag_id = tag_id
            if tag_id in self._chips:
                self._chips[tag_id].set_selected(True)
            search_text = self._tag_search_text.get(tag_id, "")
            if search_text:
                self.tag_selected.emit(search_text)

    def _on_context_menu(self, tag_id: int) -> None:
        menu = QMenu(self)
        act_delete = menu.addAction("删除标签")
        action = menu.exec(self.cursor().pos())
        if action == act_delete:
            reply = QMessageBox.question(
                self,
                "删除标签",
                "将从所有文件中移除该标签，确定删除吗？",
            )
            if reply == QMessageBox.Yes:
                was_selected = self._selected_tag_id == tag_id
                delete_tag(self._db_uri, tag_id)
                if was_selected:
                    self._selected_tag_id = None
                self.tag_deleted.emit(tag_id)
                self.reload()
