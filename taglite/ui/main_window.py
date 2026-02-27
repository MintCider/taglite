"""Main window: toolbar + QSplitter three-column layout + status bar."""

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QWidget,
)

from taglite.config import ConfigManager
from taglite.core.library import list_libraries, scan_library
from taglite.db.engine import init_db
from taglite.ui.dir_tree import DirTree
from taglite.ui.file_list import FileList
from taglite.ui.library_manager import LibraryManagerDialog
from taglite.ui.metadata_panel import MetadataPanel
from taglite.ui.scan_worker import ScanWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TagLite")
        self.resize(1150, 720)

        self._cfg = ConfigManager()
        self._db_uri = self._cfg.default_backend_uri
        init_db(self._db_uri)

        self._setup_toolbar()
        self._setup_panels()
        self._setup_statusbar()
        self._connect_signals()

        # Show library manager on first launch if no libraries
        libs = list_libraries(self._db_uri)
        if not libs:
            QTimer.singleShot(0, self._open_library_manager)
        else:
            self._dir_tree.reload(self._db_uri)

    # ---- Toolbar ----
    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._act_add_lib = QAction(
            self.style().standardIcon(QStyle.SP_DirOpenIcon), "添加库", self
        )
        self._act_scan = QAction(
            self.style().standardIcon(QStyle.SP_BrowserReload), "刷新扫描", self
        )

        toolbar.addAction(self._act_add_lib)
        scan_action = toolbar.addAction(self._act_scan)

        # Make the scan button icon-only (#7)
        scan_btn = toolbar.widgetForAction(self._act_scan)
        if scan_btn:
            scan_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)

        # Right-side spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # Search bar (#8)
        self._search_bar = QLineEdit()
        self._search_bar.setObjectName("searchBar")
        self._search_bar.setPlaceholderText("搜索文件…")
        self._search_bar.setFixedWidth(220)
        toolbar.addWidget(self._search_bar)

        self.addToolBar(toolbar)

        self._act_add_lib.triggered.connect(self._open_library_manager)
        self._act_scan.triggered.connect(self._rescan_all)

    # ---- Three-column layout ----
    def _setup_panels(self) -> None:
        self._dir_tree = DirTree()
        self._file_list = FileList(self._db_uri)
        self._meta_panel = MetadataPanel(self._db_uri)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._dir_tree)
        splitter.addWidget(self._file_list)
        splitter.addWidget(self._meta_panel)
        splitter.setSizes([200, 580, 300])
        splitter.setHandleWidth(1)

        self.setCentralWidget(splitter)

    # ---- Status bar ----
    def _setup_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._update_status()

    def _update_status(self, msg: str | None = None) -> None:
        if msg:
            self._statusbar.showMessage(msg)
        else:
            libs = list_libraries(self._db_uri)
            self._statusbar.showMessage(f"  {len(libs)} 个库已加载")

    # ---- Signal connections ----
    def _connect_signals(self) -> None:
        self._dir_tree.directory_selected.connect(self._on_directory_selected)
        self._file_list.file_selected.connect(self._meta_panel.show_file)
        self._file_list.tags_changed.connect(self._on_tags_changed)
        self._file_list.file_opened.connect(self._on_file_opened)
        self._meta_panel.tags_changed.connect(self._on_tags_changed_from_panel)
        self._search_bar.textChanged.connect(self._file_list.set_filter)

    def _on_directory_selected(self, library_id: int, rel_path: str) -> None:
        self._file_list.show_directory(library_id, rel_path)
        self._meta_panel.clear()

    def _on_tags_changed(self) -> None:
        """Tags changed in file list (via context menu) — refresh metadata panel."""
        self._meta_panel.refresh()

    def _on_tags_changed_from_panel(self) -> None:
        """Tags changed in metadata panel — refresh file list."""
        self._file_list.refresh()

    def _on_file_opened(self, filename: str) -> None:
        """Show status bar message when a file is opened (#5)."""
        self._statusbar.showMessage(f"正在打开 {filename}…", 3000)

    # ---- Library manager ----
    def _open_library_manager(self) -> None:
        dlg = LibraryManagerDialog(self._db_uri, self)
        dlg.exec()

        if dlg.needs_full_reload:
            self._dir_tree.reload(self._db_uri)
        else:
            if dlg.removed_lib_ids:
                for lib_id in dlg.removed_lib_ids:
                    self._dir_tree.remove_library(lib_id)
            if dlg.added_lib_ids:
                for lib_id in dlg.added_lib_ids:
                    self._dir_tree.add_library(self._db_uri, lib_id)

        if dlg.added_lib_ids or dlg.removed_lib_ids or dlg.needs_full_reload:
            self._update_status()

    # ---- Rescan ----
    def _rescan_all(self) -> None:
        libs = list_libraries(self._db_uri)
        if not libs:
            return
        self._act_scan.setEnabled(False)
        self._update_status("扫描中…")

        self._scan_worker = ScanWorker(self._db_uri, libs)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self) -> None:
        self._act_scan.setEnabled(True)
        self._dir_tree.reload(self._db_uri)
        self._file_list.refresh()
        self._update_status("扫描完成")
