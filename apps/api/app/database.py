"""Database configuration and SQLAlchemy session management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from apps.api.app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


def get_db():
    """Provide a database session for a request."""
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
