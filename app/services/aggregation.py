from datetime import date
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine
from app.db.sql import load_sql


def aggregate_daily(start_date: date, end_date: date, ppm_max: float) -> None:
    sql = load_sql("aggregate_daily.sql")

    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        conn.execute(
            text(sql),
            {
                "start_date": start_date,
                "end_date": end_date,
                "ppm_max": ppm_max,
            },
        )