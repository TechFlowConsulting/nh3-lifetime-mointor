from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.session import build_engine, build_session_factory

_settings = Settings.load()
_engine = build_engine(_settings)
_SessionLocal = build_session_factory(_engine)


def get_settings() -> Settings:
    return _settings


def get_db() -> Session:
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
