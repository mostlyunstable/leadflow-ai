"""
Global Pytest Configuration and Test Fixtures.
Provides isolated in-memory test databases, FastAPI test clients,
and multi-tenant test organizations and credentials.
"""

import os
import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Force testing environment before importing app modules
os.environ["ENVIRONMENT"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-min-32-chars-strictly-for-testing"
os.environ["ENCRYPTION_KEY"] = "54eO49uV2JgI7e9FqQ3P6x7V0A5b2N1M4K8L9O2P3Q="
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from core.config import settings
from core.security import hash_password, create_access_token
from database.models import Base, Organization, User, Membership, UserRole
from database.database import get_db_session
from main import app

# Shared test engine
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

import database.database as db_mod
db_mod.engine = test_engine
db_mod.SessionLocal = TestingSessionLocal


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create all tables before each test and drop them after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated database session for a test."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden database session dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def tenant_a(db_session: Session):
    """Seed Tenant A (Organization A + Owner User A)."""
    org = Organization(name="Acme Corp", slug="acme", is_active=True)
    db_session.add(org)
    db_session.flush()

    user = User(
        email="alice@acme.com",
        password_hash=hash_password("password123"),
        full_name="Alice Owner",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=UserRole.OWNER,
    )
    db_session.add(membership)
    db_session.commit()

    token = create_access_token(user_id=user.id, organization_id=org.id, role="owner")
    return {
        "org": org,
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def tenant_b(db_session: Session):
    """Seed Tenant B (Organization B + Owner User B) for cross-tenant isolation tests."""
    org = Organization(name="Beta Corp", slug="beta", is_active=True)
    db_session.add(org)
    db_session.flush()

    user = User(
        email="bob@beta.com",
        password_hash=hash_password("password456"),
        full_name="Bob Beta",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=UserRole.OWNER,
    )
    db_session.add(membership)
    db_session.commit()

    token = create_access_token(user_id=user.id, organization_id=org.id, role="owner")
    return {
        "org": org,
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }
