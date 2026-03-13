from __future__ import annotations

from sqlalchemy import text
from datetime import datetime, timezone

from app.core.settings import Settings
from app.db.session import Base, build_engine
from app.models import aux  # noqa: F401  (register models)


def main():
    settings = Settings.load()
    engine = build_engine(settings)

    # garante schema
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.postgres.schema};"))

    Base.metadata.create_all(engine)

    print("OK: tabelas auxiliares criadas/confirmadas.")


if __name__ == "__main__":
    main()
