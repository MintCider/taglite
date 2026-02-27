"""Application configuration: data directory and backend registry."""

import json
import platform
from pathlib import Path

_APP_NAME = "TagLite"


def get_app_data_dir() -> Path:
    """Return the platform-specific app data directory, creating it if needed."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(
            __import__("os").environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        )
    else:  # Linux / other
        base = Path.home() / ".local" / "share"
    path = base / _APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return get_app_data_dir() / "config.json"


def _default_db_uri() -> str:
    db_path = get_app_data_dir() / "default.db"
    return f"sqlite:///{db_path}"


class ConfigManager:
    """Manages backend registry in config.json."""

    def __init__(self) -> None:
        self._path = _config_path()
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text("utf-8"))
        # First launch: create default backend
        data = {
            "default_backend_id": 1,
            "backends": [
                {"id": 1, "name": "本地默认", "uri": _default_db_uri()},
            ],
        }
        self._save(data)
        return data

    def _save(self, data: dict | None = None) -> None:
        if data is not None:
            self._data = data
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8"
        )

    def _next_id(self) -> int:
        ids = [b["id"] for b in self._data["backends"]]
        return max(ids) + 1 if ids else 1

    @property
    def default_backend_uri(self) -> str:
        bid = self._data["default_backend_id"]
        for b in self._data["backends"]:
            if b["id"] == bid:
                return b["uri"]
        raise ValueError("Default backend not found")

    def list_backends(self) -> list[dict]:
        return list(self._data["backends"])

    def add_backend(self, name: str, uri: str | None = None) -> dict:
        """Add a new backend. If uri is None, create a new SQLite file."""
        new_id = self._next_id()
        if uri is None:
            db_path = get_app_data_dir() / f"backend_{new_id}.db"
            uri = f"sqlite:///{db_path}"
        backend = {"id": new_id, "name": name, "uri": uri}
        self._data["backends"].append(backend)
        self._save()
        return backend

    def remove_backend(self, backend_id: int) -> None:
        self._data["backends"] = [
            b for b in self._data["backends"] if b["id"] != backend_id
        ]
        if self._data["default_backend_id"] == backend_id:
            if self._data["backends"]:
                self._data["default_backend_id"] = self._data["backends"][0]["id"]
            else:
                self._data["default_backend_id"] = None
        self._save()

    def get_backend_uri(self, backend_id: int) -> str:
        for b in self._data["backends"]:
            if b["id"] == backend_id:
                return b["uri"]
        raise ValueError(f"Backend {backend_id} not found")
