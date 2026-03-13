from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from app.models import Sensor, Nh3DailyAgg, SensorCalibrationPoint


@dataclass(frozen=True)
class FormulaResult:
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


EOL_SENSITIVITY = 30.0  # fim de vida em 30%


def _latest_sa(session: Session, sensor_id: int, as_of: date) -> float | None:
    q = (
        select(SensorCalibrationPoint.sa_percent)
        .where(SensorCalibrationPoint.sensor_id == sensor_id)
        .where(SensorCalibrationPoint.calibration_date <= as_of)
        .order_by(desc(SensorCalibrationPoint.calibration_date))
        .limit(1)
    )
    return session.execute(q).scalar_one_or_none()


def _first_day(session: Session, sensor_id: int) -> date | None:
    q = select(func.min(Nh3DailyAgg.day)).where(Nh3DailyAgg.sensor_id == sensor_id)
    return session.execute(q).scalar_one_or_none()


def compute_for_day(
    session: Session,
    sensor_id: int,
    as_of: date,
    td_days: int,
    fallback_sa_percent: float = 100.0,
) -> FormulaResult:
    # Ct
    ct = session.execute(
        select(Nh3DailyAgg.ct_percent)
        .where(Nh3DailyAgg.sensor_id == sensor_id)
        .where(Nh3DailyAgg.day == as_of)
    ).scalar_one_or_none()
    if ct is None:
        raise ValueError("Sem Ct% para este dia (rode a agregação diária primeiro).")
    ct = float(ct)

    sensor = session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValueError("Sensor não encontrado.")

    # B = dias decorridos
    if sensor.instalation_date is not None:
        start = sensor.instalation_date
    else:
        start = _first_day(session, sensor_id)
        if start is None:
            raise ValueError("Sem dados suficientes para determinar B.")
    b_days = max(0, (as_of - start).days + 1)

    sa = _latest_sa(session, sensor_id, as_of)
    if sa is None:
        sa = fallback_sa_percent
    sa = float(sa)

    # Fórmulas do fabricante
    lt = td_days / 70.0
    lc = lt * (100.0 - ct) / 100.0 if ct is not None else lt
    # Proteções numéricas
    lc = max(1e-9, lc)

    sc = 100.0 - (b_days / lc)
    s = min(sa, sc)
    d = max(0.0, (s - EOL_SENSITIVITY) * lc)

    return FormulaResult(
        sensor_id=sensor_id,
        day=as_of,
        td_days=td_days,
        ct_percent=ct,
        b_days=b_days,
        sa_percent=sa,
        lt_days=lt,
        lc_days=lc,
        sc_percent=sc,
        s_percent=s,
        d_days_remaining=d,
    )
