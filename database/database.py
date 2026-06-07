"""
Database Engine & Session Management.
Provides sync SQLAlchemy engine, session factory, and initialization.
"""

import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from config.settings import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

# ── Engine ───────────────────────────────────────────────────────────────────

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=300,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

# Enable WAL mode for SQLite (better concurrent read/write)
if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# ── Session Factory ──────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_session() -> Session:
    """Context manager for database sessions with auto commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session():
    """FastAPI dependency for database session injection."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Initialization ───────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist.
    Note: For production, use Alembic migrations instead of create_all().
    """
    logger.info("Initializing database tables (create_all)...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully.")
