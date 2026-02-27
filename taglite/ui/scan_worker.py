"""Background worker for library scanning."""

from PySide6.QtCore import QThread, Signal

from taglite.core.library import scan_library


class ScanWorker(QThread):
    """Run scan_library in a background thread to avoid blocking the UI."""

    finished = Signal()

    def __init__(self, db_uri: str, libraries: list, parent=None) -> None:
        super().__init__(parent)
        self._db_uri = db_uri
        self._libraries = libraries

    def run(self) -> None:
        for lib in self._libraries:
            scan_library(self._db_uri, lib.id, lib.root_path)
        self.finished.emit()
