"""Left panel: directory tree built from DB data."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileIconProvider,
    QFrame,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from taglite.core.library import get_files_in_directory, get_library, list_libraries
from taglite.db.models import File

ICON_PROVIDER = QFileIconProvider()

# Custom roles for storing data on tree items
ROLE_LIBRARY_ID = Qt.UserRole + 1
ROLE_REL_PATH = Qt.UserRole + 2


class _DirTreeView(QTreeView):
    """QTreeView subclass: draws only expand/collapse arrows, no branch lines."""

    def drawBranches(self, painter, rect, index):
        # Fill entire branch area with background — no selection highlight, no artifacts
        painter.fillRect(rect, self.palette().window())

        model = self.model()
        if not model or not model.hasChildren(index):
            return  # Leaf items: clean background only

        # Compute depth
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()

        indent = self.indentation()
        # Arrow column: at the item's own depth level
        arrow_x = rect.x() + depth * indent
        arrow_w = indent
        arrow_rect = QRectF(arrow_x, rect.y(), arrow_w, rect.height())
        cx = arrow_rect.center().x()
        cy = arrow_rect.center().y()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().placeholderText())

        arrow_size = 3.5
        if self.isExpanded(index):
            # Down arrow ▼
            painter.drawPolygon([
                QPointF(cx - arrow_size, cy - arrow_size * 0.5),
                QPointF(cx + arrow_size, cy - arrow_size * 0.5),
                QPointF(cx, cy + arrow_size * 0.5),
            ])
        else:
            # Right arrow ▶
            painter.drawPolygon([
                QPointF(cx - arrow_size * 0.5, cy - arrow_size),
                QPointF(cx + arrow_size * 0.5, cy),
                QPointF(cx - arrow_size * 0.5, cy + arrow_size),
            ])

        painter.restore()


class DirTree(QWidget):
    """Directory tree panel. Emits directory_selected(library_id, rel_path)."""

    directory_selected = Signal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(180)
        self._db_uri: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._model = QStandardItemModel()
        self._tree = _DirTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setFrameShape(QFrame.NoFrame)
        self._tree.setAnimated(True)
        self._tree.clicked.connect(self._on_clicked)

        layout.addWidget(self._tree)

    def reload(self, db_uri: str) -> None:
        """Rebuild the entire tree from DB."""
        self._db_uri = db_uri
        self._model.clear()
        root = self._model.invisibleRootItem()

        libraries = list_libraries(db_uri)
        for lib in libraries:
            lib_item = QStandardItem(
                ICON_PROVIDER.icon(QFileIconProvider.Folder), lib.name
            )
            lib_item.setEditable(False)
            lib_item.setData(lib.id, ROLE_LIBRARY_ID)
            lib_item.setData("", ROLE_REL_PATH)
            root.appendRow(lib_item)
            self._build_subtree(db_uri, lib.id, "", lib_item)

        # Only expand top-level library nodes, keep subdirectories collapsed
        for i in range(root.rowCount()):
            self._tree.expand(self._model.indexFromItem(root.child(i)))

    def add_library(self, db_uri: str, library_id: int) -> None:
        """Incrementally add a single library subtree to the tree."""
        self._db_uri = db_uri
        lib = get_library(db_uri, library_id)
        if not lib:
            return

        root = self._model.invisibleRootItem()
        lib_item = QStandardItem(
            ICON_PROVIDER.icon(QFileIconProvider.Folder), lib.name
        )
        lib_item.setEditable(False)
        lib_item.setData(lib.id, ROLE_LIBRARY_ID)
        lib_item.setData("", ROLE_REL_PATH)
        root.appendRow(lib_item)
        self._build_subtree(db_uri, lib.id, "", lib_item)
        self._tree.expand(self._model.indexFromItem(lib_item))

    def remove_library(self, library_id: int) -> None:
        """Remove a library node from the tree by library_id."""
        root = self._model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item and item.data(ROLE_LIBRARY_ID) == library_id:
                root.removeRow(i)
                return

    def _build_subtree(
        self, db_uri: str, library_id: int, parent_rel: str, parent_item: QStandardItem
    ) -> None:
        """Recursively add subdirectories to the tree."""
        children = get_files_in_directory(db_uri, library_id, parent_rel)
        dirs = sorted(
            [f for f in children if f.is_directory], key=lambda f: f.filename.lower()
        )
        for d in dirs:
            item = QStandardItem(
                ICON_PROVIDER.icon(QFileIconProvider.Folder), d.filename
            )
            item.setEditable(False)
            item.setData(library_id, ROLE_LIBRARY_ID)
            item.setData(d.relative_path, ROLE_REL_PATH)
            parent_item.appendRow(item)
            self._build_subtree(db_uri, library_id, d.relative_path, item)

    def _on_clicked(self, index) -> None:
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        lib_id = item.data(ROLE_LIBRARY_ID)
        rel_path = item.data(ROLE_REL_PATH)
        if lib_id is not None:
            self.directory_selected.emit(lib_id, rel_path or "")
