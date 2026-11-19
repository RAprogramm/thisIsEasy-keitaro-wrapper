"""Engine, session factory, and request-scoped session dependency."""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session]:
    """Yield a request-scoped session and roll back if the request failed."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        logger.exception("request failed; rolling back session")
        db.rollback()
        raise
    finally:
        db.close()
