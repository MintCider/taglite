"""Library creation and directory scanning."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from taglite.db.engine import init_db, session_scope
from taglite.db.models import File, Library


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    missing: int = 0
    skipped_dirs: list[str] = field(default_factory=list)


def create_library_record(db_uri: str, name: str, root_path: str) -> Library:
    """Create a library DB record only (no scan). Returns the Library object."""
    init_db(db_uri)
    root = str(Path(root_path).resolve())
    with session_scope(db_uri) as session:
        lib = Library(name=name, root_path=root)
        session.add(lib)
        session.flush()
        lib_id = lib.id
    with session_scope(db_uri) as session:
        return session.get(Library, lib_id)


def create_library(db_uri: str, name: str, root_path: str) -> Library:
    """Create a library record and run initial scan."""
    lib = create_library_record(db_uri, name, root_path)
    scan_library(db_uri, lib.id, lib.root_path)
    with session_scope(db_uri) as session:
        return session.get(Library, lib.id)


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

    if not root.exists():
        return ScanResult(skipped_dirs=[str(root)])

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
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            ctime = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
            if rel in existing:
                f = existing[rel]
                f.last_seen = now
                f.file_size = None if is_dir else stat.st_size
                f.file_mtime = mtime
                f.file_ctime = ctime
                f.is_missing = False
                result.updated += 1
            else:
                f = File(
                    library_id=library_id,
                    relative_path=rel,
                    filename=fname,
                    file_size=None if is_dir else stat.st_size,
                    file_extension=None if is_dir else ext,
                    file_mtime=mtime,
                    file_ctime=ctime,
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


def list_libraries(db_uri: str, *, active_only: bool = True) -> list[Library]:
    """Return libraries in the database. By default only active ones."""
    with session_scope(db_uri) as session:
        stmt = select(Library)
        if active_only:
            stmt = stmt.where(Library.is_active == True)  # noqa: E712
        return list(session.scalars(stmt))


def get_library(db_uri: str, library_id: int) -> Library | None:
    """Get a single library by ID."""
    with session_scope(db_uri) as session:
        return session.get(Library, library_id)


def delete_library(db_uri: str, library_id: int) -> None:
    """Delete a library and all its files/tags (cascade)."""
    with session_scope(db_uri) as session:
        lib = session.get(Library, library_id)
        if lib:
            session.delete(lib)


def set_library_active(db_uri: str, library_id: int, active: bool) -> None:
    """Toggle a library's is_active flag."""
    with session_scope(db_uri) as session:
        lib = session.get(Library, library_id)
        if lib:
            lib.is_active = active


def update_library_path(db_uri: str, library_id: int, new_root_path: str) -> None:
    """Update a library's root_path."""
    root = str(Path(new_root_path).resolve())
    with session_scope(db_uri) as session:
        lib = session.get(Library, library_id)
        if lib:
            lib.root_path = root


def get_files_in_directory(
    db_uri: str, library_id: int, dir_relative_path: str
) -> list[File]:
    """Get direct children (files + subdirs) of a directory.

    dir_relative_path="" means library root.
    """
    with session_scope(db_uri) as session:
        all_files = list(
            session.scalars(
                select(File).where(
                    File.library_id == library_id,
                    File.is_missing == False,  # noqa: E712
                )
            )
        )
    # Filter to direct children of dir_relative_path
    prefix = dir_relative_path.rstrip("/\\")
    results = []
    for f in all_files:
        rel = f.relative_path
        if prefix:
            # Must start with prefix + separator
            if not rel.startswith(prefix + "/") and not rel.startswith(prefix + "\\"):
                continue
            remainder = rel[len(prefix) + 1 :]
        else:
            remainder = rel
        # Direct child: no more separators
        if "/" not in remainder and "\\" not in remainder:
            results.append(f)
    return results
