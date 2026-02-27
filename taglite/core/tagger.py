"""Tag CRUD and file tagging operations."""

from datetime import datetime, timezone

from sqlalchemy import select

from taglite.db.engine import session_scope
from taglite.db.models import File, FileTag, Tag


def parse_tag_input(text: str) -> tuple[str, str]:
    """Parse user input into (key, value).

    'project=Alpha' → ('project', 'Alpha')
    '重要'           → ('', '重要')
    """
    if "=" in text:
        key, _, value = text.partition("=")
        return key.strip(), value.strip()
    return "", text.strip()


def create_tag(
    db_uri: str, library_id: int, key: str, value: str, color: str | None = None
) -> Tag:
    with session_scope(db_uri) as session:
        tag = Tag(library_id=library_id, key=key, value=value, color=color)
        session.add(tag)
        session.flush()
        tag_id = tag.id
    with session_scope(db_uri) as session:
        return session.get(Tag, tag_id)


def get_or_create_tag(
    db_uri: str, library_id: int, key: str, value: str, color: str | None = None
) -> Tag:
    with session_scope(db_uri) as session:
        tag = session.scalar(
            select(Tag).where(
                Tag.library_id == library_id, Tag.key == key, Tag.value == value
            )
        )
        if tag:
            tag_id = tag.id
        else:
            tag = Tag(library_id=library_id, key=key, value=value, color=color)
            session.add(tag)
            session.flush()
            tag_id = tag.id
    with session_scope(db_uri) as session:
        return session.get(Tag, tag_id)


def list_tags(db_uri: str, library_id: int) -> list[Tag]:
    with session_scope(db_uri) as session:
        return list(
            session.scalars(select(Tag).where(Tag.library_id == library_id))
        )


def update_tag(
    db_uri: str,
    tag_id: int,
    *,
    key: str | None = None,
    value: str | None = None,
    color: str | None = ...,
) -> Tag:
    with session_scope(db_uri) as session:
        tag = session.get(Tag, tag_id)
        if tag is None:
            raise ValueError(f"Tag {tag_id} not found")
        if key is not None:
            tag.key = key
        if value is not None:
            tag.value = value
        if color is not ...:
            tag.color = color
    with session_scope(db_uri) as session:
        return session.get(Tag, tag_id)


def delete_tag(db_uri: str, tag_id: int) -> None:
    with session_scope(db_uri) as session:
        tag = session.get(Tag, tag_id)
        if tag:
            session.delete(tag)


def tag_file(db_uri: str, file_id: int, tag_id: int) -> None:
    """Tag a file. Idempotent — no error if already tagged."""
    with session_scope(db_uri) as session:
        existing = session.get(FileTag, (file_id, tag_id))
        if not existing:
            ft = FileTag(
                file_id=file_id,
                tag_id=tag_id,
                tagged_at=datetime.now(timezone.utc),
            )
            session.add(ft)


def untag_file(db_uri: str, file_id: int, tag_id: int) -> None:
    """Remove a tag from a file. Idempotent."""
    with session_scope(db_uri) as session:
        ft = session.get(FileTag, (file_id, tag_id))
        if ft:
            session.delete(ft)


def get_file_tags(db_uri: str, file_id: int) -> list[Tag]:
    with session_scope(db_uri) as session:
        return list(
            session.scalars(
                select(Tag)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .where(FileTag.file_id == file_id)
            )
        )


def get_files_by_tag(db_uri: str, tag_id: int) -> list[File]:
    with session_scope(db_uri) as session:
        return list(
            session.scalars(
                select(File)
                .join(FileTag, FileTag.file_id == File.id)
                .where(FileTag.tag_id == tag_id)
            )
        )
