from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from sklearn.ensemble import RandomForestRegressor

from app.models import Nh3DailyAgg, SensorCalibrationPoint
from app.services.features import add_rolling_features


MODEL_DIR = Path(__file__).resolve().parents[2] / "artifacts"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "rf_daily_loss.joblib"


FEATURES = [
    "ct_percent",
    "nh3_avg",
    "humidity_avg",
    "fan_speed_avg",
    "ct_percent_ma7",
    "ct_percent_ma30",
    "nh3_avg_ma7",
    "nh3_avg_ma30",
    "humidity_avg_ma7",
    "humidity_avg_ma30",
]


@dataclass(frozen=True)
class TrainResult:
    rows: int
    model_path: str


def _load_daily(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            Nh3DailyAgg.sensor_id,
            Nh3DailyAgg.day,
            Nh3DailyAgg.ct_percent,
            Nh3DailyAgg.nh3_avg,
            Nh3DailyAgg.humidity_avg,
            Nh3DailyAgg.fan_speed_avg,
        )
    ).all()
    df = pd.DataFrame(rows, columns=["sensor_id", "day", "ct_percent", "nh3_avg", "humidity_avg", "fan_speed_avg"])
    if df.empty:
        return df
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


def _load_calib(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            SensorCalibrationPoint.sensor_id,
            SensorCalibrationPoint.calibration_date,
            SensorCalibrationPoint.sa_percent,
        )
    ).all()
    df = pd.DataFrame(rows, columns=["sensor_id", "calibration_date", "sa_percent"])
    if df.empty:
        return df
    df["calibration_date"] = pd.to_datetime(df["calibration_date"]).dt.date
    df["sa_percent"] = df["sa_percent"].astype(float)
    return df


def build_training_set(session: Session) -> pd.DataFrame:
    daily = _load_daily(session)
    calib = _load_calib(session)

    if daily.empty or calib.empty:
        return pd.DataFrame()

    daily = add_rolling_features(daily)

    # Cria rótulo: perda diária estimada entre calibrações.
    # Para cada sensor, para cada intervalo [calib_i, calib_{i+1}], a perda diária = (Sa_i - Sa_{i+1}) / delta_days.
    rows = []
    for sensor_id, g in calib.sort_values(["sensor_id", "calibration_date"]).groupby("sensor_id"):
        g = g.sort_values("calibration_date")
        for i in range(len(g) - 1):
            d0 = g.iloc[i]["calibration_date"]
            d1 = g.iloc[i + 1]["calibration_date"]
            sa0 = float(g.iloc[i]["sa_percent"])
            sa1 = float(g.iloc[i + 1]["sa_percent"])
            delta = (d1 - d0).days
            if delta <= 0:
                continue
            daily_loss = (sa0 - sa1) / float(delta)

            # Seleciona dias no intervalo (inclusive d0, exclusivo d1)
            mask = (daily["sensor_id"] == sensor_id) & (daily["day"] >= d0) & (daily["day"] < d1)
            chunk = daily.loc[mask].copy()
            if chunk.empty:
                continue
            chunk["daily_loss"] = daily_loss
            rows.append(chunk)

    if not rows:
        return pd.DataFrame()
    train = pd.concat(rows, ignore_index=True)

    # Limpeza mínima
    train = train.dropna(subset=["ct_percent"])
    return train


def train(session: Session, n_estimators: int = 300, random_state: int = 42) -> TrainResult:
    train_df = build_training_set(session)
    if train_df.empty:
        raise ValueError(
            "Base de treino vazia. Verifique: (1) nh3_daily_agg preenchida, (2) sensor_calibration_points com 2+ calibrações por sensor."
        )

    X = train_df.reindex(columns=FEATURES).fillna(0.0)
    y = train_df["daily_loss"].astype(float).values

    model = RandomForestRegressor(
        n_estimators=n_estimators,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X, y)
    joblib.dump({"model": model, "features": FEATURES}, MODEL_PATH)

    return TrainResult(rows=int(len(train_df)), model_path=str(MODEL_PATH))


def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Modelo não treinado. Rode /api/ml/train ou scripts/train_ml.py.")
    payload = joblib.load(MODEL_PATH)
    return payload["model"], payload["features"]


def forecast_daily_loss(df_features: pd.DataFrame) -> np.ndarray:
    model, feats = load_model()
    X = df_features.reindex(columns=feats).fillna(0.0)
    return model.predict(X)
