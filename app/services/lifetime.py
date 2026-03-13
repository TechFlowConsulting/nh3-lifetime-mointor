from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine
from typing import Optional

@dataclass(frozen=True)
class LifetimeParams:
    td_days: float = 710.0
    eol_percent: float = 30.0


SQL_READ_LIFETIME = """
SELECT
  sensor_id, day,
  ct_percent, td_days, eol_percent,
  b_days, lt_days_per_1pct, lc_days_per_1pct,
  sa_percent, sc_percent,
  dt_days, da_days
FROM public.nh3_lifetime_daily
WHERE day >= :start_day
  AND day <  :end_day
  AND (:sensor_id IS NULL OR sensor_id = :sensor_id)
ORDER BY sensor_id, day
LIMIT :limit;
"""

SQL_READ_AGG = """
SELECT
  sensor_id,
  day,
  ct_percent
FROM public.nh3_daily_agg
WHERE day >= :start_day
  AND day <  :end_day
ORDER BY sensor_id, day;
"""

SQL_UPSERT_LIFE = """
INSERT INTO public.nh3_lifetime_daily
(
  sensor_id, day,
  ct_percent, td_days, eol_percent,
  b_days, lt_days_per_1pct, lc_days_per_1pct,
  sa_percent, sc_percent,
  dt_days, da_days,
  created_at
)
VALUES
(
  :sensor_id, :day,
  :ct_percent, :td_days, :eol_percent,
  :b_days, :lt, :lc,
  :sa, :sc,
  :dt, :da,
  now()
)
ON CONFLICT (sensor_id, day) DO NOTHING SET
  ct_percent       = EXCLUDED.ct_percent,
  td_days          = EXCLUDED.td_days,
  eol_percent      = EXCLUDED.eol_percent,
  b_days           = EXCLUDED.b_days,
  lt_days_per_1pct = EXCLUDED.lt_days_per_1pct,
  lc_days_per_1pct = EXCLUDED.lc_days_per_1pct,
  sa_percent       = EXCLUDED.sa_percent,
  sc_percent       = EXCLUDED.sc_percent,
  dt_days          = EXCLUDED.dt_days,
  da_days          = EXCLUDED.da_days,
  created_at       = now();
"""




def _safe_div(a: float, b: Optional[float], *, default: float = 0.0) -> float:
    if b is None:
        return default
    if abs(b) <= 1e-12:
        return default
    return a / b


def run_lifetime_daily(start_day: date, end_day: date, params: LifetimeParams) -> dict[str, Any]:
    """
    Calcula Lt/Lc/Sa/Sc/Dt/Da por dia e por sensor, baseado na fórmula do fabricante.

    Fórmulas (conforme sua imagem):
      Lt = (1% * Td) / 70%  => Lt = (0.01 * Td) / 0.70
      Lc = ((100 - Ct) * Lt) / 100
      Sa = 100 - (B / Lt)
      Sc = 100 - (B / Lc)
      Dt = (Sa - EOL) * Lt
      Da = (Sc - EOL) * Lc

    Onde:
      Ct = ct_percent (0..100) do dia
      B  = operating days (contador de dias do sensor dentro do período, 1..N)
      EOL = eol_percent (ex.: 30)
    """
    settings = Settings.load()
    engine = build_engine(settings)

    td_days = float(params.td_days)
    eol = float(params.eol_percent)

    # Lt fixo p/ o cálculo (depende só do Td)
    lt = (0.01 * td_days) / 0.70

    rows_written = 0
    sensors_processed = 0

    with engine.begin() as conn:
        rows = conn.execute(
            text(SQL_READ_AGG),
            {"start_day": start_day, "end_day": end_day},
        ).mappings().all()

        if not rows:
            return {
                "sensors_processed": 0,
                "rows_written": 0,
                "td_days": td_days,
                "lt_days_per_1pct": lt,
                "eol_percent": eol,
            }

        current_sensor = None
        b_days = 0

        for r in rows:
            sensor_id = int(r["sensor_id"])
            day = r["day"]
            ct = r.get("ct_percent", None)

            if current_sensor != sensor_id:
                current_sensor = sensor_id
                b_days = 0
                sensors_processed += 1

            b_days += 1

            ct_val = float(ct) if ct is not None else None

            # Lc depende do Ct
            lc = None
            if ct_val is not None:
                lc = ((100.0 - ct_val) * lt) / 100.0
                # Evita Lc ~ 0 (Ct ~ 100) derrubar tudo
                if lc <= 1e-9:
                    lc = 1e-9

            # Sa (sem gás) e Sc (com gás)
            sa = 100.0 - _safe_div(float(b_days), lt, default=0.0)
            sa = max(0.0, sa)

            sc = 100.0 - _safe_div(float(b_days), lc, default=0.0)
            sc = max(0.0, sc)

            # Dt / Da (dias restantes até EOL)
            dt = None
            if sa is not None:
                dt = max(0.0, (sa - eol) * lt)

            da = None
            if sc is not None and lc is not None:
                da = max(0.0, (sc - eol) * lc)

            conn.execute(
                text(SQL_UPSERT_LIFE),
                {
                    "sensor_id": sensor_id,
                    "day": day,
                    "ct_percent": ct_val,
                    "td_days": td_days,
                    "eol_percent": eol,
                    "b_days": b_days,
                    "lt": lt,
                    "lc": lc,
                    "sa": sa,
                    "sc": sc,
                    "dt": dt,
                    "da": da,
                },
            )
            rows_written += 1

    return {
        "sensors_processed": sensors_processed,
        "rows_written": rows_written,
        "td_days": td_days,
        "lt_days_per_1pct": lt,
        "eol_percent": eol,
    }