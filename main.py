"""TagLite entry point."""

import sys

from taglite.ui.app import create_app
from taglite.ui.main_window import MainWindow


def main() -> None:
    app = create_app()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
