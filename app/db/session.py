from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.settings import Settings


class Base(DeclarativeBase):
    pass


def build_engine(settings: Settings):
    return create_engine(
        settings.postgres.sqlalchemy_url,
        pool_pre_ping=True,
    )


def build_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
