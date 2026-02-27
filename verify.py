"""End-to-end verification for Phase 1 core skeleton."""

import os
import tempfile
from pathlib import Path

from taglite.db.engine import init_db, session_scope
from taglite.core.library import create_library, scan_library
from taglite.core.tagger import (
    create_tag,
    delete_tag,
    get_file_tags,
    get_files_by_tag,
    get_or_create_tag,
    list_tags,
    parse_tag_input,
    tag_file,
    untag_file,
    update_tag,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        lib_root = Path(tmpdir) / "my_library"
        lib_root.mkdir()

        # Create some test files
        (lib_root / "doc1.txt").write_text("hello")
        (lib_root / "doc2.pdf").write_text("world")
        sub = lib_root / "subdir"
        sub.mkdir()
        (sub / "image.png").write_bytes(b"\x89PNG")
        # Hidden file/dir should be skipped
        (lib_root / ".hidden").write_text("skip me")
        hidden_dir = lib_root / ".git"
        hidden_dir.mkdir()
        (hidden_dir / "config").write_text("skip")

        # Use an in-memory-like temp SQLite for isolation
        db_path = Path(tmpdir) / "test.db"
        db_uri = f"sqlite:///{db_path}"
        init_db(db_uri)

        # --- 1. Create library + initial scan ---
        print("=== Create Library ===")
        lib = create_library(db_uri, "测试库", str(lib_root))
        print(f"Library: {lib}")

        with session_scope(db_uri) as s:
            from taglite.db.models import File
            files = list(s.scalars(__import__("sqlalchemy").select(File).where(File.library_id == lib.id)))
            print(f"Indexed entries: {len(files)} (files + dirs)")
            assert len(files) == 4, f"Expected 4 entries (3 files + 1 dir), got {len(files)}"
            for f in files:
                kind = "DIR " if f.is_directory else "FILE"
                print(f"  [{kind}] {f.relative_path}  size={f.file_size}  ext={f.file_extension}")

        # --- 2. parse_tag_input ---
        print("\n=== Parse Tag Input ===")
        assert parse_tag_input("project=Alpha") == ("project", "Alpha")
        assert parse_tag_input("重要") == ("", "重要")
        assert parse_tag_input("status=done") == ("status", "done")
        print("parse_tag_input OK")

        # --- 3. Tag CRUD ---
        print("\n=== Tag CRUD ===")
        t1 = create_tag(db_uri, lib.id, "", "重要")
        t2 = create_tag(db_uri, lib.id, "project", "Alpha")
        print(f"Created: {t1}, {t2}")

        t1_dup = get_or_create_tag(db_uri, lib.id, "", "重要")
        assert t1_dup.id == t1.id, "get_or_create should return existing"
        print("get_or_create_tag idempotent OK")

        tags = list_tags(db_uri, lib.id)
        assert len(tags) == 2
        print(f"list_tags: {tags}")

        update_tag(db_uri, t1.id, color="#ff0000")
        with session_scope(db_uri) as s:
            t1_updated = s.get(__import__("taglite.db.models", fromlist=["Tag"]).Tag, t1.id)
            assert t1_updated.color == "#ff0000"
        print("update_tag OK")

        # --- 4. Tag files ---
        print("\n=== Tag Files ===")
        with session_scope(db_uri) as s:
            from sqlalchemy import select as sel
            from taglite.db.models import File as F
            all_files = list(s.scalars(sel(F).where(F.library_id == lib.id)))
            file_map = {f.filename: f.id for f in all_files}

        doc1_id = file_map["doc1.txt"]
        doc2_id = file_map["doc2.pdf"]

        tag_file(db_uri, doc1_id, t1.id)
        tag_file(db_uri, doc1_id, t2.id)
        tag_file(db_uri, doc2_id, t1.id)
        # Idempotent
        tag_file(db_uri, doc1_id, t1.id)
        print("tag_file OK (idempotent)")

        doc1_tags = get_file_tags(db_uri, doc1_id)
        assert len(doc1_tags) == 2, f"Expected 2 tags on doc1, got {len(doc1_tags)}"
        print(f"doc1.txt tags: {doc1_tags}")

        files_with_t1 = get_files_by_tag(db_uri, t1.id)
        assert len(files_with_t1) == 2
        print(f"Files with '重要': {[f.filename for f in files_with_t1]}")

        # Untag
        untag_file(db_uri, doc1_id, t2.id)
        doc1_tags = get_file_tags(db_uri, doc1_id)
        assert len(doc1_tags) == 1
        print("untag_file OK")

        # --- 5. Tag a directory ---
        print("\n=== Tag Directory ===")
        subdir_id = file_map["subdir"]
        tag_file(db_uri, subdir_id, t1.id)
        subdir_tags = get_file_tags(db_uri, subdir_id)
        assert len(subdir_tags) == 1
        print(f"subdir tags: {subdir_tags}")

        # --- 6. Rescan: detect missing files ---
        print("\n=== Rescan (missing detection) ===")
        os.remove(lib_root / "doc2.pdf")
        result = scan_library(db_uri, lib.id, str(lib_root))
        print(f"Rescan result: added={result.added}, updated={result.updated}, missing={result.missing}")
        assert result.missing == 1, f"Expected 1 missing, got {result.missing}"

        with session_scope(db_uri) as s:
            from taglite.db.models import File as F2
            missing = list(s.scalars(sel(F2).where(F2.library_id == lib.id, F2.is_missing == True)))
            assert len(missing) == 1
            assert missing[0].filename == "doc2.pdf"
        print("is_missing detection OK")

        # --- 7. Delete tag (cascade) ---
        print("\n=== Delete Tag ===")
        delete_tag(db_uri, t1.id)
        tags = list_tags(db_uri, lib.id)
        assert len(tags) == 1
        doc1_tags = get_file_tags(db_uri, doc1_id)
        assert len(doc1_tags) == 0, "FileTag should be cascade-deleted"
        print("delete_tag + cascade OK")

        print("\n✅ All checks passed!")


if __name__ == "__main__":
    main()
