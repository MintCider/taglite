"""Database engine and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from taglite.db.models import Base

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}


def get_engine(db_uri: str) -> Engine:
    """Get or create a cached engine for the given URI."""
    if db_uri not in _engines:
        connect_args = {}
        if db_uri.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engines[db_uri] = create_engine(db_uri, connect_args=connect_args)
    return _engines[db_uri]


def init_db(db_uri: str) -> None:
    """Create all tables for the given database URI."""
    engine = get_engine(db_uri)
    Base.metadata.create_all(engine)


def get_session_factory(db_uri: str) -> sessionmaker[Session]:
    if db_uri not in _session_factories:
        engine = get_engine(db_uri)
        _session_factories[db_uri] = sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factories[db_uri]


@contextmanager
def session_scope(db_uri: str) -> Generator[Session, None, None]:
    """Context manager: auto commit/rollback/close."""
    factory = get_session_factory(db_uri)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
