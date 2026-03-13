from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class SensorOut(BaseModel):
    id: int
    tag_name: str
    type_sensor: int
    modbus_address: int
    modbus_port: int
    clp_id: int
    instalation_date: date | None = None


class FormulaOut(BaseModel):
    sensor_id: int
    day: date
    td_days: int
    ct_percent: float
    b_days: int
    sa_percent: float
    lt_days: float
    lc_days: float
    sc_percent: float
    s_percent: float
    d_days_remaining: float


class CalibrationIn(BaseModel):
    calibration_date: date
    sa_percent: float
    note: str | None = None


class CalibrationOut(CalibrationIn):
    sensor_id: int
