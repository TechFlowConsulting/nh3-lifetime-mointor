from __future__ import annotations

import argparse
import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor-id", type=int, required=True)
    return ap.parse_args()


def main():
    args = parse_args()
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT day, ct_percent, nh3_avg, nh3_max, humidity_avg
                FROM public.nh3_daily_agg
                WHERE sensor_id = :sid
                ORDER BY day
                
                """
            ),
            {"sid": args.sensor_id},
        ).all()

    df = pd.DataFrame(rows, columns=["day", "ct_percent", "nh3_avg", "nh3_max", "humidity_avg"])
    if df.empty:
        raise SystemExit("Sem dados em nh3_daily_agg. Rode scripts/aggregate_daily.py.")

    df["day"] = pd.to_datetime(df["day"])

    plt.figure(figsize=(12, 5))
    plt.plot(df["day"], df["ct_percent"])
    plt.title(f"Sensor {args.sensor_id} - Ct% (média diária)")
    plt.xlabel("Dia")
    plt.ylabel("Ct%")
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 5))
    plt.plot(df["day"], df["nh3_max"])
    plt.title(f"Sensor {args.sensor_id} - NH3 max diário (ppm)")
    plt.xlabel("Dia")
    plt.ylabel("ppm")
    plt.tight_layout()
    plt.show()

    if df["humidity_avg"].notna().any():
        plt.figure(figsize=(12, 5))
        plt.plot(df["day"], df["humidity_avg"])
        plt.title(f"Sensor {args.sensor_id} - Umidade média diária (%)")
        plt.xlabel("Dia")
        plt.ylabel("%")
        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    main()
