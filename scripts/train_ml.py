from __future__ import annotations

from app.core.settings import Settings
from app.db.session import build_engine, build_session_factory
from app.services.ml_model import train


def main():
    settings = Settings.load()
    engine = build_engine(settings)
    SessionLocal = build_session_factory(engine)
    with SessionLocal() as session:
        out = train(session)
        print(out)


if __name__ == "__main__":
    main()
