"""Main window: toolbar + QSplitter three-column layout + status bar."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from taglite.config import ConfigManager
from taglite.core.library import list_libraries, scan_library
from taglite.core.search import execute_search, parse_search
from taglite.db.engine import init_db
from taglite.ui.dir_tree import DirTree
from taglite.ui.file_list import FileList
from taglite.ui.library_manager import LibraryManagerDialog
from taglite.ui.metadata_panel import MetadataPanel
from taglite.ui.scan_worker import ScanWorker
from taglite.ui.search_panel import AdvancedSearchPanel
from taglite.ui.tag_browser import TagBrowser


class ExpandButton(QWidget):
    """Custom-painted expand/collapse button with a triangle arrow."""

    clicked = Signal(bool)  # emits checked state

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self._hovered = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("高级搜索")

    def isChecked(self) -> bool:
        return self._checked

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())

        # Hover background
        if self._hovered:
            painter.setBrush(QColor(128, 128, 128, 30))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)

        # Draw triangle arrow
        cx, cy = rect.center().x(), rect.center().y()
        color = self.palette().windowText().color()
        color.setAlpha(180)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)

        if self._checked:
            # ▲ up arrow
            tri = QPolygonF([QPointF(cx - 4, cy + 2), QPointF(cx + 4, cy + 2), QPointF(cx, cy - 3)])
        else:
            # ▼ down arrow
            tri = QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx + 4, cy - 2), QPointF(cx, cy + 3)])
        painter.drawPolygon(tri)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self.update()
            self.clicked.emit(self._checked)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()


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
            self._tag_browser.reload(self._db_uri)

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
        self._search_bar.setPlaceholderText("搜索文件… (Enter 搜索)")
        self._search_bar.setFixedWidth(250)
        toolbar.addWidget(self._search_bar)

        # Advanced search expand button
        self._adv_btn = ExpandButton()
        toolbar.addWidget(self._adv_btn)

        self.addToolBar(toolbar)

        self._act_add_lib.triggered.connect(self._open_library_manager)
        self._act_scan.triggered.connect(self._rescan_all)

    # ---- Three-column layout ----
    def _setup_panels(self) -> None:
        self._dir_tree = DirTree()
        self._tag_browser = TagBrowser(self._db_uri)
        self._file_list = FileList(self._db_uri)
        self._meta_panel = MetadataPanel(self._db_uri)
        self._search_panel = AdvancedSearchPanel(self._db_uri)

        # Left panel: vertical splitter with DirTree on top, TagBrowser on bottom
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self._dir_tree)
        left_splitter.addWidget(self._tag_browser)
        left_splitter.setSizes([400, 200])
        left_splitter.setHandleWidth(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_splitter)
        splitter.addWidget(self._file_list)
        splitter.addWidget(self._meta_panel)
        splitter.setSizes([200, 580, 300])
        splitter.setHandleWidth(1)

        # Style individual handles directly (avoid cascading to child widgets)
        for sp in (splitter, left_splitter):
            for i in range(1, sp.count()):
                handle = sp.handle(i)
                if handle:
                    handle.setStyleSheet("background: rgba(128,128,128,80);")

        # Wrap in a vertical layout: search panel + splitter
        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._search_panel, 0)   # no stretch — only takes needed height
        vbox.addWidget(splitter, 1)              # gets all remaining space

        self.setCentralWidget(central)

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
        self._file_list.directory_entered.connect(self._on_directory_entered)
        self._meta_panel.tags_changed.connect(self._on_tags_changed_from_panel)
        self._tag_browser.tag_deleted.connect(self._on_tag_deleted)
        self._tag_browser.tag_selected.connect(self._on_tag_browser_selected)
        self._tag_browser.tag_deselected.connect(self._on_tag_browser_deselected)
        self._search_bar.returnPressed.connect(self._on_search)
        self._adv_btn.clicked.connect(self._toggle_advanced_search)
        self._search_panel.search_requested.connect(self._on_advanced_search)

    def _on_directory_selected(self, library_id: int, rel_path: str) -> None:
        self._search_bar.clear()
        self._tag_browser.clear_selection()
        self._file_list.show_directory(library_id, rel_path)
        self._meta_panel.clear()

    def _on_directory_entered(self, library_id: int, rel_path: str) -> None:
        """User double-clicked a folder in the file list. Navigate into it."""
        self._search_bar.clear()
        self._tag_browser.clear_selection()
        self._file_list.show_directory(library_id, rel_path)
        self._dir_tree.select_path(library_id, rel_path)
        self._meta_panel.clear()

    def _on_tags_changed(self) -> None:
        """Tags changed in file list (via context menu) — refresh metadata panel + tag browser."""
        self._meta_panel.refresh()
        self._tag_browser.reload()
        self._file_list.clear_search_cache()
        if self._search_panel.isVisible():
            self._search_panel.reload_tags()

    def _on_tags_changed_from_panel(self) -> None:
        """Tags changed in metadata panel — refresh file list + tag browser."""
        self._file_list.clear_search_cache()
        self._file_list.refresh()
        self._tag_browser.reload()
        if self._search_panel.isVisible():
            self._search_panel.reload_tags()

    def _on_tag_deleted(self, tag_id: int) -> None:
        """A tag was deleted from the tag browser."""
        self._file_list.clear_search_cache()
        self._file_list.refresh()
        self._meta_panel.refresh()

    def _on_file_opened(self, filename: str) -> None:
        """Show status bar message when a file is opened (#5)."""
        self._statusbar.showMessage(f"正在打开 {filename}…", 3000)

    # ---- Search ----
    def _on_search(self) -> None:
        text = self._search_bar.text().strip()
        if not text:
            # Empty search → restore last directory view
            self._restore_directory_view()
            return

        # Check LRU cache
        cached = self._file_list.get_cached_search(text)
        if cached:
            files, tags = cached
            query = parse_search(text)
            self._file_list.show_search_results(files, tags, query)
            self._meta_panel.clear()
            self._update_status(f"搜索结果: {len(files)} 个文件")
            return

        query = parse_search(text)
        if not query.parse_ok:
            self._update_status(f"搜索语法有误：{query.error}")
            return

        files, tags = execute_search(self._db_uri, query)
        self._file_list.cache_search(text, files, tags)
        self._file_list.show_search_results(files, tags, query)
        self._meta_panel.clear()
        self._update_status(f"搜索结果: {len(files)} 个文件")

    def _on_tag_browser_selected(self, search_text: str) -> None:
        """Tag browser clicked a tag → populate search bar and search."""
        self._search_bar.setText(search_text)
        self._on_search()

    def _on_tag_browser_deselected(self) -> None:
        """Tag browser deselected → clear search bar and restore directory."""
        self._search_bar.clear()
        self._restore_directory_view()

    def _restore_directory_view(self) -> None:
        """Restore the last directory view (exit search mode)."""
        if self._file_list._current_library_id is not None:
            self._file_list.show_directory(
                self._file_list._current_library_id,
                self._file_list._current_rel_path,
            )

    # ---- Advanced search panel ----
    def _toggle_advanced_search(self, checked: bool) -> None:
        self._search_panel.setVisible(checked)
        if checked:
            self._search_panel.reload_tags(self._db_uri)

    def _on_advanced_search(self, search_text: str) -> None:
        """Advanced panel applied → write to search bar and execute."""
        self._search_bar.setText(search_text)
        if search_text:
            self._on_search()
        else:
            self._restore_directory_view()

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
            self._tag_browser.reload()

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
        self._tag_browser.reload()
        self._update_status("扫描完成")
