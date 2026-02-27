"""SQLAlchemy 2.0 ORM models for TagLite."""

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Library(Base):
    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    root_path: Mapped[str] = mapped_column(String, nullable=False)

    tags: Mapped[list["Tag"]] = relationship(
        back_populates="library", cascade="all, delete-orphan"
    )
    files: Mapped[list["File"]] = relationship(
        back_populates="library", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Library(id={self.id}, name={self.name!r})>"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("library_id", "key", "value", name="uq_tag_lib_key_val"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False, default="")
    value: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)

    library: Mapped["Library"] = relationship(back_populates="tags")
    file_tags: Mapped[list["FileTag"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        label = f"{self.key}={self.value}" if self.key else self.value
        return f"<Tag(id={self.id}, {label})>"


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("library_id", "relative_path", name="uq_file_lib_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    file_extension: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    is_directory: Mapped[bool] = mapped_column(default=False)
    is_missing: Mapped[bool] = mapped_column(default=False)

    library: Mapped["Library"] = relationship(back_populates="files")
    file_tags: Mapped[list["FileTag"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<File(id={self.id}, {self.relative_path!r})>"


class FileTag(Base):
    __tablename__ = "file_tags"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id"), primary_key=True
    )
    tagged_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    file: Mapped["File"] = relationship(back_populates="file_tags")
    tag: Mapped["Tag"] = relationship(back_populates="file_tags")
