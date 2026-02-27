"""Center panel: file list table with name/mtime/size/type/tags columns."""

from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QFileInfo,
    QModelIndex,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QFrame,
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from taglite.core.library import get_files_in_directory, get_library
from taglite.core.tagger import get_tags_for_files
from taglite.db.models import File, Tag
from taglite.utils.sort_key import pinyin_sort_key

ICON_PROVIDER = QFileIconProvider()

# Custom roles
SORT_ROLE = Qt.UserRole + 10
TAG_DATA_ROLE = Qt.UserRole + 11  # list[tuple[str, str|None]] — (display, color)
PATH_DATA_ROLE = Qt.UserRole + 12  # str — relative_path (search mode only)


def _format_size(n: int | None) -> str:
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024**2:.1f} MB"


def _tag_display(tag: Tag) -> str:
    if tag.key:
        return f"{tag.key}={tag.value}"
    return tag.value


class FileTableModel(QAbstractTableModel):
    HEADERS = ["名称", "修改时间", "大小", "类型", "标签"]

    def __init__(self) -> None:
        super().__init__()
        self._files: list[File] = []
        self._tags: dict[int, list[Tag]] = {}
        self._root_path: str = ""
        self._lib_roots: dict[int, str] = {}
        self._show_path: bool = False

    def load(self, files: list[File], tags: dict[int, list[Tag]], root_path: str = "", lib_roots: dict[int, str] | None = None) -> None:
        self.beginResetModel()
        self._files = files
        self._tags = tags
        self._root_path = root_path
        if lib_roots is not None:
            self._lib_roots = lib_roots
        self.endResetModel()

    def get_file(self, row: int) -> File | None:
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._files)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 5

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        f = self._files[row]

        if role == Qt.DisplayRole:
            if col == 0:
                return f.filename
            if col == 1:
                if f.file_mtime:
                    return f.file_mtime.strftime("%Y-%m-%d %H:%M")
                return ""
            if col == 2:
                return _format_size(f.file_size) if not f.is_directory else ""
            if col == 3:
                if f.is_directory:
                    return "文件夹"
                return (f.file_extension or "").lstrip(".").upper()
            if col == 4:
                tags = self._tags.get(f.id, [])
                return ", ".join(_tag_display(t) for t in tags) if tags else ""

        if role == Qt.DecorationRole and col == 0:
            if f.is_directory:
                return ICON_PROVIDER.icon(QFileIconProvider.Folder)
            root = self._root_path or self._lib_roots.get(f.library_id, "")
            if root:
                abs_path = str(Path(root) / f.relative_path)
                return ICON_PROVIDER.icon(QFileInfo(abs_path))
            return ICON_PROVIDER.icon(QFileIconProvider.File)

        if role == Qt.TextAlignmentRole:
            if col == 2:
                return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == SORT_ROLE:
            dir_flag = 0 if f.is_directory else 1
            if col == 0:
                if self._show_path:
                    return (dir_flag, pinyin_sort_key(f.relative_path))
                return (dir_flag, pinyin_sort_key(f.filename))
            if col == 1:
                return (dir_flag, f.file_mtime or datetime.min)
            if col == 2:
                return (dir_flag, f.file_size or 0)
            if col == 3:
                return (dir_flag, (f.file_extension or "").lstrip(".").lower())
            if col == 4:
                tags = self._tags.get(f.id, [])
                return (dir_flag, ", ".join(_tag_display(t) for t in tags))

        if role == TAG_DATA_ROLE and col == 4:
            tags = self._tags.get(f.id, [])
            return [(_tag_display(t), t.color) for t in tags]

        if role == PATH_DATA_ROLE and col == 0 and self._show_path:
            return f.relative_path

        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None


class NamePathDelegate(QStyledItemDelegate):
    """Adjusts row height for search results to accommodate a path line below."""

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        path = index.data(PATH_DATA_ROLE)
        if path:
            fm = QFontMetrics(option.font)
            hint.setHeight(fm.height() * 2 + 12)
        return hint


class FileTableView(QTableView):
    """QTableView that paints full-width path subtitles below rows in search mode."""

    def paintEvent(self, event):
        super().paintEvent(event)
        self._paint_path_overlays()

    def _paint_path_overlays(self):
        model = self.model()
        if not model or model.rowCount() == 0:
            return

        # Quick check: is this search mode?
        if not model.index(0, 0).data(PATH_DATA_ROLE):
            return

        painter = QPainter(self.viewport())

        # Small font for path line
        path_font = self.font()
        px = path_font.pixelSize()
        path_font.setPixelSize(max(px - 2, 10) if px > 0 else 10)
        painter.setFont(path_font)
        fm = QFontMetrics(path_font)

        vp_rect = self.viewport().rect()

        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            path = idx.data(PATH_DATA_ROLE)
            if not path:
                continue

            cell_rect = self.visualRect(idx)
            if not cell_rect.isValid() or not vp_rect.intersects(cell_rect):
                continue

            # Path at bottom of the row, spanning full viewport width
            path_y = cell_rect.bottom() - fm.height() - 2
            indent = cell_rect.left() + 32  # align roughly with text after icon
            path_rect = QRectF(indent, path_y, vp_rect.width() - indent - 8, fm.height())

            # Color depends on selection state
            selected = self.selectionModel().isRowSelected(row, idx.parent())
            if selected:
                color = self.palette().highlightedText().color()
                color.setAlpha(180)
            else:
                color = self.palette().placeholderText().color()
            painter.setPen(color)

            elided = fm.elidedText(path, Qt.ElideMiddle, int(path_rect.width()))
            painter.drawText(path_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

        painter.end()


class TagChipDelegate(QStyledItemDelegate):
    """Paints tag chips in the tags column using QPainter."""

    CHIP_H_PAD = 6
    CHIP_V_PAD = 2
    CHIP_RADIUS = 10
    CHIP_SPACING = 4
    CHIP_TEXT_H_MARGIN = 6
    CHIP_TEXT_V_MARGIN = 1

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        # Draw default background (selection highlight, alternating rows)
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()
        # Paint background only, not the text
        opt = QStyleOptionViewItem(option)
        opt.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)

        tag_data = index.data(TAG_DATA_ROLE)
        if not tag_data:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        fm = QFontMetrics(option.font)

        x = option.rect.left() + self.CHIP_H_PAD
        y_center = option.rect.center().y()
        max_x = option.rect.right() - self.CHIP_H_PAD

        for display_text, color_hex in tag_data:
            text_width = fm.horizontalAdvance(display_text)
            chip_w = text_width + self.CHIP_TEXT_H_MARGIN * 2
            chip_h = fm.height() + self.CHIP_TEXT_V_MARGIN * 2 + 2

            # Check if chip fits; show ellipsis if not
            if x + chip_w > max_x:
                ellipsis_w = fm.horizontalAdvance("\u2026")
                if x + ellipsis_w <= max_x:
                    painter.setPen(QColor(128, 128, 128))
                    painter.drawText(
                        int(x), int(y_center - fm.height() / 2),
                        int(ellipsis_w), fm.height(),
                        Qt.AlignCenter, "\u2026"
                    )
                break

            qc = QColor(color_hex) if color_hex else QColor("#0078d4")
            r, g, b = qc.red(), qc.green(), qc.blue()

            chip_rect = QRectF(
                x, y_center - chip_h / 2, chip_w, chip_h
            )

            # Background
            painter.setBrush(QBrush(QColor(r, g, b, 25)))
            painter.setPen(QPen(QColor(r, g, b, 76), 1))
            painter.drawRoundedRect(chip_rect, self.CHIP_RADIUS, self.CHIP_RADIUS)

            # Text
            painter.setPen(QColor(color_hex or "#0078d4"))
            text_rect = chip_rect.adjusted(self.CHIP_TEXT_H_MARGIN, 0, -self.CHIP_TEXT_H_MARGIN, 0)
            painter.drawText(text_rect, Qt.AlignCenter, display_text)

            x += chip_w + self.CHIP_SPACING

        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), 28))
        return hint


class FileSortProxy(QSortFilterProxyModel):
    """Sort proxy that uses Python-native comparison for tuple sort keys."""

    def lessThan(self, left, right):
        l = left.data(SORT_ROLE)
        r = right.data(SORT_ROLE)
        if l is None:
            return True
        if r is None:
            return False
        try:
            return l < r
        except TypeError:
            return str(l) < str(r)


class FileList(QWidget):
    """File list panel. Emits file_selected(file_id), tags_changed(), file_opened(str)."""

    file_selected = Signal(int)
    tags_changed = Signal()
    file_opened = Signal(str)
    directory_entered = Signal(int, str)  # (library_id, rel_path)

    def __init__(self, db_uri: str, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self._current_library_id: int | None = None
        self._current_rel_path: str = ""
        self._current_root_path: str = ""
        self._search_mode: bool = False
        self._current_query = None  # SearchQuery cached for refresh
        self._search_cache: OrderedDict[str, tuple[list, dict]] = OrderedDict()
        self._CACHE_MAX = 3

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._model = FileTableModel()
        self._proxy = FileSortProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)

        self._table = FileTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setFrameShape(QFrame.NoFrame)
        self._table.setSortingEnabled(True)
        self._table.setWordWrap(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)

        # Tag chip delegate for column 4
        self._tag_delegate = TagChipDelegate(self._table)
        self._table.setItemDelegateForColumn(4, self._tag_delegate)

        # Name+path delegate for column 0 (shows subtitle path in search mode)
        self._name_delegate = NamePathDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._name_delegate)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.resizeSection(0, 260)
        header.resizeSection(1, 140)
        header.resizeSection(2, 70)
        header.resizeSection(3, 70)

        # Default sort: column 0 ascending (dirs first via SORT_ROLE)
        self._table.sortByColumn(0, Qt.AscendingOrder)

        # Store default row height for restoring after search mode
        self._default_row_height = self._table.verticalHeader().defaultSectionSize()

        layout.addWidget(self._table)

        self._table.selectionModel().selectionChanged.connect(self._on_selection)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

    def set_filter(self, text: str) -> None:
        """Filter file list by name substring."""
        self._proxy.setFilterFixedString(text)

    def show_directory(self, library_id: int, rel_path: str) -> None:
        self._search_mode = False
        self._current_query = None
        self._model._show_path = False
        self._current_library_id = library_id
        self._current_rel_path = rel_path
        lib = get_library(self._db_uri, library_id)
        self._current_root_path = lib.root_path if lib else ""
        # Restore normal row height
        self._table.verticalHeader().setDefaultSectionSize(self._default_row_height)
        self._load_files()

    def show_search_results(self, files: list, tags: dict, query=None) -> None:
        """Switch to search result mode."""
        self._search_mode = True
        self._current_query = query
        self._model._show_path = True
        # Taller rows to fit path line below normal content
        fm = QFontMetrics(self._table.font())
        self._table.verticalHeader().setDefaultSectionSize(fm.height() * 2 + 12)
        # Compute lib_roots for file icons
        lib_roots = self._resolve_lib_roots(files)
        self._model.load(files, tags, lib_roots=lib_roots)

    def clear_search_cache(self) -> None:
        """Clear the LRU search cache (called when data changes)."""
        self._search_cache.clear()

    def cache_search(self, key: str, files: list, tags: dict) -> None:
        """Store a search result in the LRU cache."""
        if key in self._search_cache:
            self._search_cache.move_to_end(key)
        else:
            self._search_cache[key] = (files, tags)
            if len(self._search_cache) > self._CACHE_MAX:
                self._search_cache.popitem(last=False)

    def get_cached_search(self, key: str):
        """Return cached (files, tags) or None."""
        if key in self._search_cache:
            self._search_cache.move_to_end(key)
            return self._search_cache[key]
        return None

    def refresh(self) -> None:
        if self._search_mode and self._current_query is not None:
            from taglite.core.search import execute_search
            self.clear_search_cache()
            files, tags = execute_search(self._db_uri, self._current_query)
            lib_roots = self._resolve_lib_roots(files)
            self._model.load(files, tags, lib_roots=lib_roots)
        elif self._current_library_id is not None:
            self._load_files()

    def _resolve_lib_roots(self, files: list) -> dict[int, str]:
        """Get library root paths for a list of files."""
        lib_ids = set(f.library_id for f in files)
        roots: dict[int, str] = {}
        for lid in lib_ids:
            lib = get_library(self._db_uri, lid)
            if lib:
                roots[lid] = lib.root_path
        return roots

    def _load_files(self) -> None:
        files = get_files_in_directory(
            self._db_uri, self._current_library_id, self._current_rel_path
        )
        file_ids = [f.id for f in files]
        tags = get_tags_for_files(self._db_uri, file_ids)
        self._model.load(files, tags, self._current_root_path)

    def _source_file(self, proxy_index: QModelIndex) -> File | None:
        source_index = self._proxy.mapToSource(proxy_index)
        return self._model.get_file(source_index.row())

    def _on_selection(self) -> None:
        indexes = self._table.selectionModel().selectedRows()
        if indexes:
            f = self._source_file(indexes[0])
            if f:
                self.file_selected.emit(f.id)

    def _on_double_click(self, index: QModelIndex) -> None:
        f = self._source_file(index)
        if not f:
            return
        if f.is_directory:
            self.directory_entered.emit(f.library_id, f.relative_path)
            return
        lib = get_library(self._db_uri, f.library_id)
        if lib:
            abs_path = Path(lib.root_path) / f.relative_path
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))
            QTimer.singleShot(1500, QApplication.restoreOverrideCursor)
            self.file_opened.emit(f.filename)

    def _on_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        f = self._source_file(index)
        if not f:
            return

        menu = QMenu(self)
        act_tag = menu.addAction("添加标签\u2026")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))

        if action == act_tag:
            from taglite.ui.tag_dialog import TagDialog

            dlg = TagDialog(self._db_uri, f.library_id, f.id, self)
            if dlg.exec():
                self.refresh()
                self.tags_changed.emit()
