from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, Numeric, Date, DateTime, String, Float, UniqueConstraint
from app.db.session import Base


class Nh3DailyAgg(Base):
    __tablename__ = "nh3_daily_agg"
    __table_args__ = (
        UniqueConstraint("sensor_id", "day", name="uq_nh3_daily_sensor_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    day: Mapped[object] = mapped_column(Date, index=True)

    samples: Mapped[int] = mapped_column(Integer)

    nh3_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    nh3_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    humidity_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fan_speed_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    ct_percent: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..100

    created_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)


class SensorCalibrationPoint(Base):
    __tablename__ = "sensor_calibration_points"
    __table_args__ = (
        UniqueConstraint("sensor_id", "calibration_date", name="uq_sensor_calib_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    calibration_date: Mapped[object] = mapped_column(Date, index=True)
    sa_percent: Mapped[float] = mapped_column(Float)  # sensibilidade calibrada (0..100)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)


class SensorCluster(Base):
    __tablename__ = "sensor_clusters"
    __table_args__ = (
        UniqueConstraint("sensor_id", name="uq_sensor_cluster_sensor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    model_version: Mapped[str] = mapped_column(String(64))
    k: Mapped[int] = mapped_column(Integer)
    cluster_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
