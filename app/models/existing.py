from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, Numeric, Boolean, Date, DateTime, String
from app.db.session import Base


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tag_name: Mapped[str] = mapped_column(String(255))
    type_sensor: Mapped[int] = mapped_column(Integer)
    modbus_address: Mapped[int] = mapped_column(Integer)
    modbus_port: Mapped[int] = mapped_column(Integer)
    clp_id: Mapped[int] = mapped_column(BigInteger)
    instalation_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    sp_saturation: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    divisor: Mapped[int] = mapped_column(Integer, default=1)


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    date: Mapped[object] = mapped_column(Date)  # dia (conforme dump)
    sensor_id: Mapped[int] = mapped_column(Integer, index=True)
    value: Mapped[float] = mapped_column(Numeric(8, 2))
    humidity: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    fan_speed: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    modbus_address: Mapped[int] = mapped_column(Integer)
    alarm_h: Mapped[bool] = mapped_column(Boolean)
    alarm_hh: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
