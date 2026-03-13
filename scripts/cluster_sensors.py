from __future__ import annotations

import argparse
from datetime import datetime
import pandas as pd
from sqlalchemy import select, text
from sklearn.cluster import KMeans

from app.core.settings import Settings
from app.db.session import build_engine
from app.models import Nh3DailyAgg


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--model-version", default="v1")
    return ap.parse_args()


def main():
    args = parse_args()
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                  sensor_id,
                  AVG(ct_percent) AS ct_mean,
                  STDDEV_POP(ct_percent) AS ct_std,
                  AVG(humidity_avg) AS rh_mean,
                  STDDEV_POP(humidity_avg) AS rh_std,
                  AVG(nh3_max) AS nh3_max_mean
                FROM public.nh3_daily_agg
                WHERE ct_percent IS NOT NULL
                GROUP BY sensor_id
                """
            )
        ).all()

        df = pd.DataFrame(rows, columns=["sensor_id", "ct_mean", "ct_std", "rh_mean", "rh_std", "nh3_max_mean"])
        if df.empty:
            raise SystemExit("Sem dados em nh3_daily_agg para clusterizar.")

        X = df[["ct_mean", "ct_std", "rh_mean", "rh_std", "nh3_max_mean"]].fillna(0.0).values
        km = KMeans(n_clusters=args.k, n_init="auto", random_state=42)
        df["cluster_id"] = km.fit_predict(X)

        # upsert
        conn.execute(text("""CREATE TABLE IF NOT EXISTS public.sensor_clusters (
            id bigserial PRIMARY KEY,
            sensor_id bigint NOT NULL UNIQUE,
            model_version varchar(64) NOT NULL,
            k integer NOT NULL,
            cluster_id integer NOT NULL,
            created_at timestamp without time zone
        );"""))
        for r in df.itertuples(index=False):
            conn.execute(
                text(
                    """
                    INSERT INTO public.sensor_clusters (sensor_id, model_version, k, cluster_id, created_at)
                    VALUES (:sensor_id, :model_version, :k, :cluster_id, NOW())
                    ON CONFLICT (sensor_id) DO UPDATE SET
                      model_version = EXCLUDED.model_version,
                      k = EXCLUDED.k,
                      cluster_id = EXCLUDED.cluster_id,
                      created_at = NOW();
                    """
                ),
                {
                    "sensor_id": int(r.sensor_id),
                    "model_version": args.model_version,
                    "k": int(args.k),
                    "cluster_id": int(r.cluster_id),
                },
            )

    print(f"OK: clusterização concluída (k={args.k}).")


if __name__ == "__main__":
    main()
