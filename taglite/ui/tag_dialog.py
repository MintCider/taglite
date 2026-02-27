"""Tag management dialog: add/remove tags with colored chips and color picker."""

from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taglite.core.tagger import (
    delete_tag,
    get_file_tags,
    get_or_create_tag,
    list_tags,
    parse_tag_input,
    tag_file,
    tag_files_recursive,
    untag_file,
    untag_files_recursive,
    update_tag,
)
from taglite.db.engine import session_scope
from taglite.db.models import File
from taglite.ui.color_picker import PRESET_COLORS, ColorPicker
from taglite.ui.flow_layout import FlowLayout
from taglite.ui.tag_chip import TagChipFrame


def _tag_display(tag) -> str:
    if tag.key:
        return f"{tag.key}={tag.value}"
    return tag.value


class TagDialog(QDialog):
    """Dialog to manage tags for a file. Shows library tags as clickable chips."""

    def __init__(self, db_uri: str, library_id: int, file_id: int, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self._library_id = library_id
        self._file_id = file_id
        self._applied = False

        # Detect if target is a directory (for recursive tag prompts)
        with session_scope(db_uri) as session:
            f = session.get(File, file_id)
            self._is_directory = f.is_directory if f else False
            self._rel_path = f.relative_path if f else ""

        self.setWindowTitle("管理标签")
        self.setMinimumSize(420, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- Create tag section ----
        create_label = QLabel("创建标签")
        create_label.setObjectName("sectionTitle")
        layout.addWidget(create_label)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("输入标签名（或 key=value 格式）")
        self._btn_create = QPushButton("创建并添加")
        self._btn_create.setObjectName("primaryBtn")
        input_row.addWidget(self._input)
        input_row.addWidget(self._btn_create)
        layout.addLayout(input_row)

        self._color_picker = ColorPicker()
        layout.addWidget(self._color_picker)

        # ---- Library tags section ----
        lib_label = QLabel("库中已有标签（单击添加到文件）")
        lib_label.setObjectName("sectionTitle")
        layout.addWidget(lib_label)

        self._lib_tags_scroll = QScrollArea()
        self._lib_tags_scroll.setWidgetResizable(True)
        self._lib_tags_scroll.setFrameShape(QFrame.NoFrame)
        self._lib_tags_scroll.setMaximumHeight(180)
        self._lib_tags_widget = QWidget()
        self._lib_tags_layout = FlowLayout(self._lib_tags_widget, h_spacing=6, v_spacing=6)
        self._lib_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._lib_tags_scroll.setWidget(self._lib_tags_widget)
        layout.addWidget(self._lib_tags_scroll)

        # ---- File tags section ----
        file_label = QLabel("当前文件标签")
        file_label.setObjectName("sectionTitle")
        layout.addWidget(file_label)

        self._file_tags_scroll = QScrollArea()
        self._file_tags_scroll.setWidgetResizable(True)
        self._file_tags_scroll.setFrameShape(QFrame.NoFrame)
        self._file_tags_scroll.setMaximumHeight(140)
        self._file_tags_widget = QWidget()
        self._file_tags_layout = FlowLayout(self._file_tags_widget, h_spacing=6, v_spacing=6)
        self._file_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._file_tags_scroll.setWidget(self._file_tags_widget)
        layout.addWidget(self._file_tags_scroll)

        # ---- Close button ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_close = QPushButton("完成")
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

        # Signals
        self._btn_create.clicked.connect(self._create_and_apply)
        self._input.returnPressed.connect(self._create_and_apply)
        self._btn_close.clicked.connect(self._finish)

        self._reload()

    def _reload(self) -> None:
        all_tags = list_tags(self._db_uri, self._library_id)
        file_tags = get_file_tags(self._db_uri, self._file_id)
        file_tag_ids = {t.id for t in file_tags}

        # Rebuild library tags chips
        self._clear_flow_layout(self._lib_tags_layout)
        for tag in all_tags:
            is_on_file = tag.id in file_tag_ids
            chip = TagChipFrame(
                _tag_display(tag),
                color=tag.color,
                tag_id=tag.id,
                dimmed=is_on_file,
                clickable=not is_on_file,
                removable=False,
            )
            if not is_on_file:
                chip.clicked.connect(lambda tid=tag.id: self._apply_tag(tid))
            chip.edit_requested.connect(lambda tid=tag.id: self._edit_tag_menu(tid))
            self._lib_tags_layout.addWidget(chip)

        # Rebuild file tags chips
        self._clear_flow_layout(self._file_tags_layout)
        for tag in file_tags:
            chip = TagChipFrame(
                _tag_display(tag),
                color=tag.color,
                tag_id=tag.id,
                removable=True,
            )
            chip.remove_requested.connect(lambda tid=tag.id: self._remove_from_file(tid))
            chip.edit_requested.connect(lambda tid=tag.id: self._edit_tag_menu(tid))
            self._file_tags_layout.addWidget(chip)

    def _clear_flow_layout(self, layout: FlowLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _auto_assign_color(self) -> str:
        used = {t.color for t in list_tags(self._db_uri, self._library_id) if t.color}
        for c in PRESET_COLORS:
            if c not in used:
                return c
        return PRESET_COLORS[len(used) % len(PRESET_COLORS)]

    def _create_and_apply(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        key, value = parse_tag_input(text)
        color = self._color_picker.current_color
        if color is None:
            color = self._auto_assign_color()
        tag = get_or_create_tag(self._db_uri, self._library_id, key, value, color=color)
        if not self._do_tag(tag.id):
            return
        self._input.clear()
        self._reload()

    def _apply_tag(self, tag_id: int) -> None:
        if not self._do_tag(tag_id):
            return
        self._reload()

    def _remove_from_file(self, tag_id: int) -> None:
        if not self._do_untag(tag_id):
            return
        self._reload()

    def _do_tag(self, tag_id: int) -> bool:
        """Tag the file (with recursive prompt for directories). Returns False if cancelled."""
        if self._is_directory:
            reply = QMessageBox.question(
                self,
                "添加标签",
                "要同时为此文件夹内所有内容添加该标签吗？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return False
            if reply == QMessageBox.Yes:
                tag_files_recursive(
                    self._db_uri, self._library_id, self._rel_path, tag_id
                )
            else:
                tag_file(self._db_uri, self._file_id, tag_id)
        else:
            tag_file(self._db_uri, self._file_id, tag_id)
        self._applied = True
        return True

    def _do_untag(self, tag_id: int) -> bool:
        """Untag the file (with recursive prompt for directories). Returns False if cancelled."""
        if self._is_directory:
            reply = QMessageBox.question(
                self,
                "移除标签",
                "要同时移除此文件夹内所有内容的该标签吗？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return False
            if reply == QMessageBox.Yes:
                untag_files_recursive(
                    self._db_uri, self._library_id, self._rel_path, tag_id
                )
            else:
                untag_file(self._db_uri, self._file_id, tag_id)
        else:
            untag_file(self._db_uri, self._file_id, tag_id)
        self._applied = True
        return True

    def _delete_lib_tag(self, tag_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "删除标签",
            "将从所有文件中移除该标签，确定删除吗？",
        )
        if reply == QMessageBox.Yes:
            delete_tag(self._db_uri, tag_id)
            self._applied = True
            self._reload()

    def _edit_tag_menu(self, tag_id: int) -> None:
        """Right-click context menu on a tag chip."""
        menu = QMenu(self)
        act_rename = menu.addAction("修改标签名\u2026")
        act_color = menu.addAction("修改颜色\u2026")
        menu.addSeparator()
        act_delete = menu.addAction("删除标签")

        action = menu.exec(self.cursor().pos())
        if action == act_rename:
            self._rename_tag(tag_id)
        elif action == act_color:
            self._change_tag_color(tag_id)
        elif action == act_delete:
            self._delete_lib_tag(tag_id)

    def _rename_tag(self, tag_id: int) -> None:
        text, ok = QInputDialog.getText(self, "修改标签名", "新名称：")
        if ok and text.strip():
            key, value = parse_tag_input(text.strip())
            update_tag(self._db_uri, tag_id, key=key, value=value)
            self._applied = True
            self._reload()

    def _change_tag_color(self, tag_id: int) -> None:
        color = QColorDialog.getColor(parent=self, title="选择颜色")
        if color.isValid():
            update_tag(self._db_uri, tag_id, color=color.name())
            self._applied = True
            self._reload()

    def _finish(self) -> None:
        if self._applied:
            self.accept()
        else:
            self.reject()
