from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# Bound to an engine by init_engine(). Request handlers and the background processor
# both open sessions from here, so the processor only ever needs a job id.
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)

_engine: Engine | None = None


def init_engine(database_url: str) -> Engine:
    """Create the engine, bind the session factory and make sure the tables exist."""
    global _engine
    if _engine is not None:
        _engine.dispose()

    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        # Background tasks run on a worker thread, not the thread that opened the connection.
        connect_args = {"check_same_thread": False, "timeout": 30}

    _engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal.configure(bind=_engine)

    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    Base.metadata.create_all(_engine)
    return _engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
