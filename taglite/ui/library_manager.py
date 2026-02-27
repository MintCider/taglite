"""Library management dialog: add / remove / rescan / toggle active / change path."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from taglite.core.library import (
    create_library_record,
    delete_library,
    get_library,
    list_libraries,
    scan_library,
    set_library_active,
    update_library_path,
)
from taglite.db.engine import init_db
from taglite.ui.scan_worker import ScanWorker


class LibraryManagerDialog(QDialog):
    def __init__(self, db_uri: str, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        init_db(self._db_uri)

        # Incremental change tracking
        self._added_lib_ids: list[int] = []
        self._removed_lib_ids: list[int] = []
        self._needs_full_reload: bool = False

        self.setWindowTitle("库管理")
        self.setMinimumSize(460, 380)

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("添加库\u2026")
        self._btn_remove = QPushButton("移除")
        self._btn_rescan = QPushButton("重新扫描")
        self._btn_toggle = QPushButton("关闭")
        self._btn_change_path = QPushButton("修改路径\u2026")
        self._btn_close = QPushButton("关闭对话框")
        self._btn_close.setObjectName("primaryBtn")

        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addWidget(self._btn_rescan)
        btn_row.addWidget(self._btn_toggle)
        btn_row.addWidget(self._btn_change_path)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

        self._btn_add.clicked.connect(self._add_library)
        self._btn_remove.clicked.connect(self._remove_library)
        self._btn_rescan.clicked.connect(self._rescan_library)
        self._btn_toggle.clicked.connect(self._toggle_active)
        self._btn_change_path.clicked.connect(self._change_path)
        self._btn_close.clicked.connect(self.accept)
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._reload_list()

    # ---- Public properties for main_window incremental update ----

    @property
    def added_lib_ids(self) -> list[int]:
        return self._added_lib_ids

    @property
    def removed_lib_ids(self) -> list[int]:
        return self._removed_lib_ids

    @property
    def needs_full_reload(self) -> bool:
        return self._needs_full_reload

    # ---- Internal ----

    def _reload_list(self) -> None:
        self._list.clear()
        self._libraries = list_libraries(self._db_uri, active_only=False)
        for lib in self._libraries:
            if lib.is_active:
                text = f"{lib.name}  \u2014  {lib.root_path}"
            else:
                text = f"{lib.name}  \u2014  {lib.root_path}  [\u5df2\u5173\u95ed]"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, lib.id)
            if not lib.is_active:
                item.setForeground(Qt.gray)
            self._list.addItem(item)
        self._update_button_states()

    def _selected_lib(self):
        """Return the currently selected Library object, or None."""
        item = self._list.currentItem()
        if not item:
            return None
        lib_id = item.data(Qt.UserRole)
        return next((l for l in self._libraries if l.id == lib_id), None)

    def _on_selection_changed(self) -> None:
        self._update_button_states()

    def _update_button_states(self) -> None:
        lib = self._selected_lib()
        has_sel = lib is not None
        self._btn_remove.setEnabled(has_sel)
        self._btn_rescan.setEnabled(has_sel)
        self._btn_toggle.setEnabled(has_sel)
        self._btn_change_path.setEnabled(has_sel)
        if lib:
            self._btn_toggle.setText("打开" if not lib.is_active else "关闭")
        else:
            self._btn_toggle.setText("关闭")

    def _add_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录")
        if not folder:
            return
        folder_path = Path(folder)
        default_name = folder_path.name

        name, ok = QInputDialog.getText(
            self, "库名称", "为这个库命名：", text=default_name
        )
        if not ok or not name.strip():
            return

        try:
            lib = create_library_record(self._db_uri, name.strip(), str(folder_path))
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))
            return

        self._added_lib_ids.append(lib.id)

        # Scan with progress
        progress = QProgressDialog("正在扫描文件\u2026", None, 0, 0, self)
        progress.setWindowTitle("扫描中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        self._scan_worker = ScanWorker(self._db_uri, [lib], self)
        self._scan_worker.finished.connect(progress.close)
        self._scan_worker.finished.connect(self._reload_list)
        self._scan_worker.start()

    def _remove_library(self) -> None:
        lib = self._selected_lib()
        if not lib:
            return

        reply = QMessageBox.question(
            self,
            "确认移除",
            f"确定要移除库「{lib.name}」吗？\n（不会删除磁盘文件，只移除索引数据）",
        )
        if reply == QMessageBox.Yes:
            lib_id = lib.id
            delete_library(self._db_uri, lib_id)
            self._removed_lib_ids.append(lib_id)
            # If it was also just added, cancel out
            if lib_id in self._added_lib_ids:
                self._added_lib_ids.remove(lib_id)
            self._reload_list()

    def _rescan_library(self) -> None:
        lib = self._selected_lib()
        if not lib:
            return

        # Check path validity
        root = Path(lib.root_path)
        if not root.exists():
            reply = QMessageBox.question(
                self,
                "路径不存在",
                f"路径 {lib.root_path} 不存在。\n是否选择新路径？",
            )
            if reply == QMessageBox.Yes:
                new_folder = QFileDialog.getExistingDirectory(self, "选择新路径")
                if new_folder:
                    update_library_path(self._db_uri, lib.id, new_folder)
                    self._needs_full_reload = True
                    self._reload_list()
                    # Re-fetch lib for scan
                    lib = get_library(self._db_uri, lib.id)
                else:
                    return
            else:
                return

        self._btn_rescan.setEnabled(False)
        self._btn_rescan.setText("扫描中\u2026")

        self._scan_worker = ScanWorker(self._db_uri, [lib], self)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_done(self) -> None:
        self._btn_rescan.setEnabled(True)
        self._btn_rescan.setText("重新扫描")
        self._reload_list()

    def _toggle_active(self) -> None:
        lib = self._selected_lib()
        if not lib:
            return
        new_active = not lib.is_active
        set_library_active(self._db_uri, lib.id, new_active)
        self._needs_full_reload = True
        self._reload_list()

    def _change_path(self) -> None:
        lib = self._selected_lib()
        if not lib:
            return
        new_folder = QFileDialog.getExistingDirectory(
            self, f"选择「{lib.name}」的新路径", lib.root_path
        )
        if not new_folder:
            return
        update_library_path(self._db_uri, lib.id, new_folder)
        self._needs_full_reload = True
        self._reload_list()
