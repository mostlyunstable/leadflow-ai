"""
Production Database Engine & Connection Lifecycle.
Supports PostgreSQL (with connection pooling) and SQLite (with WAL & foreign key enforcement).
Provides robust session management and automatic seed initialization.
"""

import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from core.config import settings
from core.security import hash_password
from database.models import Base, Organization, User, Membership, UserRole

logger = logging.getLogger("leadflow.database")

# ── Connection Engine Configuration ──────────────────────────────────────────

connect_args = {}
pool_kwargs = {}

if "sqlite" in settings.DATABASE_URL.lower():
    connect_args["check_same_thread"] = False
else:
    # Production PostgreSQL pool configuration
    pool_kwargs = {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": True,
    }

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=connect_args,
    **pool_kwargs,
)

# SQLite pragmas for development/testing reliability
if "sqlite" in settings.DATABASE_URL.lower():
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
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency for request-scoped database sessions."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Initialization & Tenant Seeding ──────────────────────────────────────────

def init_db(seed_default_tenant: bool = True):
    """
    Initialize database schema and seed default tenant/admin user if empty.
    Note: Schema migrations in CI/CD should execute `alembic upgrade head`.
    """
    logger.info("Verifying database schema...")
    Base.metadata.create_all(bind=engine)

    if seed_default_tenant:
        with get_session() as session:
            # Check if default organization exists
            org = session.query(Organization).filter_by(slug="default").first()
            if not org:
                logger.info("Seeding initial default organization...")
                org = Organization(
                    name="Default Organization",
                    slug="default",
                    is_active=True,
                )
                session.add(org)
                session.flush()

            # Check if default admin user exists
            admin_email = "admin@leadflow.local"
            user = session.query(User).filter_by(email=admin_email).first()
            if not user:
                logger.info("Seeding initial admin user (admin@leadflow.local)...")
                user = User(
                    email=admin_email,
                    password_hash=hash_password("admin123456"),
                    full_name="LeadFlow Administrator",
                    is_active=True,
                    is_superuser=True,
                )
                session.add(user)
                session.flush()

                membership = Membership(
                    user_id=user.id,
                    organization_id=org.id,
                    role=UserRole.OWNER,
                )
                session.add(membership)
                logger.info("Default organization and administrator seeded successfully.")
