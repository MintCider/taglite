"""Library creation and directory scanning."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from taglite.db.engine import init_db, session_scope
from taglite.db.models import File, Library


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    missing: int = 0
    skipped_dirs: list[str] = field(default_factory=list)


def create_library(db_uri: str, name: str, root_path: str) -> Library:
    """Create a library record and run initial scan."""
    init_db(db_uri)
    root = str(Path(root_path).resolve())
    with session_scope(db_uri) as session:
        lib = Library(name=name, root_path=root)
        session.add(lib)
        session.flush()
        lib_id = lib.id

    scan_library(db_uri, lib_id, root)

    with session_scope(db_uri) as session:
        return session.get(Library, lib_id)


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def scan_library(db_uri: str, library_id: int, root_path: str) -> ScanResult:
    """Walk the directory tree and sync files table.

    - New files → insert
    - Existing files → update last_seen / file_size, clear is_missing
    - Disappeared files → mark is_missing=True
    """
    result = ScanResult()
    now = datetime.now(timezone.utc)
    root = Path(root_path)

    # Collect all relative paths on disk
    disk_files: dict[str, tuple[os.stat_result, bool]] = {}  # rel -> (stat, is_dir)
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories (mutate in-place to prune walk)
        dirnames[:] = [d for d in dirnames if not _is_hidden(d)]
        rel_dir = Path(dirpath).relative_to(root)
        # Index non-hidden subdirectories
        for dname in dirnames:
            rel = str(rel_dir / dname) if str(rel_dir) != "." else dname
            full = Path(dirpath) / dname
            try:
                disk_files[rel] = (full.stat(), True)
            except OSError:
                continue
        for fname in filenames:
            if _is_hidden(fname):
                continue
            rel = str(rel_dir / fname) if str(rel_dir) != "." else fname
            full = Path(dirpath) / fname
            try:
                disk_files[rel] = (full.stat(), False)
            except OSError:
                continue

    with session_scope(db_uri) as session:
        # Load existing file records for this library
        existing = {
            f.relative_path: f
            for f in session.scalars(
                select(File).where(File.library_id == library_id)
            )
        }

        # Upsert files found on disk
        for rel, (stat, is_dir) in disk_files.items():
            ext = Path(rel).suffix.lower() or None
            fname = Path(rel).name
            if rel in existing:
                f = existing[rel]
                f.last_seen = now
                f.file_size = None if is_dir else stat.st_size
                f.is_missing = False
                result.updated += 1
            else:
                f = File(
                    library_id=library_id,
                    relative_path=rel,
                    filename=fname,
                    file_size=None if is_dir else stat.st_size,
                    file_extension=None if is_dir else ext,
                    is_directory=is_dir,
                    last_seen=now,
                    is_missing=False,
                )
                session.add(f)
                result.added += 1

        # Mark missing files
        for rel, f in existing.items():
            if rel not in disk_files and not f.is_missing:
                f.is_missing = True
                result.missing += 1

    return result
