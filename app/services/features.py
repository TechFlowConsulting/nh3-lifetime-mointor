from __future__ import annotations

import pandas as pd


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    # df must have columns: sensor_id, day, ct_percent, humidity_avg, nh3_avg
    df = df.sort_values(["sensor_id", "day"]).copy()
    for col in ["ct_percent", "humidity_avg", "nh3_avg"]:
        if col in df.columns:
            df[f"{col}_ma7"] = df.groupby("sensor_id")[col].transform(lambda s: s.rolling(7, min_periods=1).mean())
            df[f"{col}_ma30"] = df.groupby("sensor_id")[col].transform(lambda s: s.rolling(30, min_periods=1).mean())
    return df
