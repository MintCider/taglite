"""Right panel: file metadata display + tag chips with add/remove."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taglite.core.library import get_library
from taglite.core.tagger import get_file_tags, parse_tag_input, untag_file, update_tag
from taglite.db.engine import session_scope
from taglite.db.models import File
from taglite.ui.flow_layout import FlowLayout
from taglite.ui.tag_chip import AddTagButton, TagChipFrame


def _tag_display(tag) -> str:
    if tag.key:
        return f"{tag.key}={tag.value}"
    return tag.value


def _format_size(n: int | None) -> str:
    if n is None:
        return "\u2014"
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024**2:.1f} MB"


class MetadataPanel(QWidget):
    """Right-side panel showing file info and tags."""

    tags_changed = Signal()

    def __init__(self, db_uri: str, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self._current_file_id: int | None = None
        self.setObjectName("metaPanel")
        self.setMinimumWidth(240)

        # Scroll area wrapping content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(0)

        scroll.setWidget(self._content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._build_empty()

    def _build_empty(self) -> None:
        self._clear_layout()
        lbl = QLabel("选择文件以查看详情")
        lbl.setObjectName("metaKey")
        lbl.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(lbl)
        self._layout.addStretch()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sublayout(item.layout())

    def _clear_sublayout(self, layout) -> None:
        while layout.count():
            sub = layout.takeAt(0)
            if sub.widget():
                sub.widget().deleteLater()
            elif sub.layout():
                self._clear_sublayout(sub.layout())

    def clear(self) -> None:
        self._current_file_id = None
        self._build_empty()

    def show_file(self, file_id: int) -> None:
        self._current_file_id = file_id
        self._render()

    def refresh(self) -> None:
        if self._current_file_id is not None:
            self._render()

    def _render(self) -> None:
        self._clear_layout()
        file_id = self._current_file_id
        if file_id is None:
            self._build_empty()
            return

        # Load file from DB
        with session_scope(self._db_uri) as session:
            f = session.get(File, file_id)
            if not f:
                self._build_empty()
                return
            filename = f.filename
            rel_path = f.relative_path
            file_size = f.file_size
            file_ext = f.file_extension
            is_dir = f.is_directory
            lib_id = f.library_id

        lib = get_library(self._db_uri, lib_id)
        tags = get_file_tags(self._db_uri, file_id)

        # Title
        title = QLabel(filename)
        title.setObjectName("panelTitle")
        self._layout.addWidget(title)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator")
        self._layout.addWidget(sep)

        # Details section
        info_title = QLabel("详细信息")
        info_title.setObjectName("sectionTitle")
        self._layout.addWidget(info_title)

        parent_dir = str(Path(rel_path).parent)
        if parent_dir == ".":
            parent_dir = lib.name if lib else ""
        else:
            parent_dir = f"{lib.name} / {parent_dir}" if lib else parent_dir

        details = [
            ("位置", parent_dir),
            ("大小", _format_size(file_size) if not is_dir else "文件夹"),
            ("类型", "文件夹" if is_dir else (file_ext or "未知").lstrip(".").upper()),
        ]
        if lib:
            abs_path = str(Path(lib.root_path) / rel_path)
            details.append(("完整路径", abs_path))

        for key, value in details:
            k = QLabel(key)
            k.setObjectName("metaKey")
            v = QLabel(value)
            v.setObjectName("metaValue")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._layout.addWidget(k)
            self._layout.addWidget(v)

        # Tags section
        tag_title = QLabel("标签")
        tag_title.setObjectName("sectionTitle")
        self._layout.addWidget(tag_title)

        tag_container = QWidget()
        tag_flow = FlowLayout(tag_container, h_spacing=6, v_spacing=6)
        tag_flow.setContentsMargins(0, 0, 0, 0)

        for tag in tags:
            chip = TagChipFrame(
                _tag_display(tag),
                color=tag.color,
                tag_id=tag.id,
                removable=True,
            )
            chip.remove_requested.connect(lambda tid=tag.id: self._remove_tag(tid))
            chip.edit_requested.connect(lambda tid=tag.id: self._edit_tag_menu(tid))
            tag_flow.addWidget(chip)

        add_btn = AddTagButton("+ 添加标签")
        add_btn.clicked.connect(self._add_tag)
        tag_flow.addWidget(add_btn)

        self._layout.addWidget(tag_container)
        self._layout.addStretch()

    def _remove_tag(self, tag_id: int) -> None:
        if self._current_file_id is None:
            return
        untag_file(self._db_uri, self._current_file_id, tag_id)
        self._render()
        self.tags_changed.emit()

    def _edit_tag_menu(self, tag_id: int) -> None:
        """Right-click context menu to edit a tag."""
        menu = QMenu(self)
        act_rename = menu.addAction("修改标签名\u2026")
        act_color = menu.addAction("修改颜色\u2026")

        action = menu.exec(self.cursor().pos())
        if action == act_rename:
            self._rename_tag(tag_id)
        elif action == act_color:
            self._change_tag_color(tag_id)

    def _rename_tag(self, tag_id: int) -> None:
        text, ok = QInputDialog.getText(self, "修改标签名", "新名称：")
        if ok and text.strip():
            key, value = parse_tag_input(text.strip())
            update_tag(self._db_uri, tag_id, key=key, value=value)
            self._render()
            self.tags_changed.emit()

    def _change_tag_color(self, tag_id: int) -> None:
        color = QColorDialog.getColor(parent=self, title="选择颜色")
        if color.isValid():
            update_tag(self._db_uri, tag_id, color=color.name())
            self._render()
            self.tags_changed.emit()

    def _add_tag(self) -> None:
        if self._current_file_id is None:
            return
        with session_scope(self._db_uri) as session:
            f = session.get(File, self._current_file_id)
            if not f:
                return
            lib_id = f.library_id

        from taglite.ui.tag_dialog import TagDialog

        dlg = TagDialog(self._db_uri, lib_id, self._current_file_id, self)
        if dlg.exec():
            self._render()
            self.tags_changed.emit()
