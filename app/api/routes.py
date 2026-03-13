from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine

# Se você já tem estes módulos, ótimo.
# Se não tiver, eu deixei fallback abaixo.
try:
    from app.services.aggregation import aggregate_daily
except Exception:  # fallback: roda SQL_AGG direto
    aggregate_daily = None

try:
    from app.services.lifetime import run_lifetime_daily, LifetimeParams
except Exception:
    run_lifetime_daily = None
    LifetimeParams = None

# Plotly (para gráficos "Grafana-like")
try:
    import plotly.graph_objects as go
except Exception:
    go = None


router = APIRouter(tags=["UI"])

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
TEMPLATES_DIR = APP_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

print("\n>>> LOADED app.ui.routes (FINAL) <<<")
print(f">>> FILE: {__file__}")
print(f">>> TEMPLATES DIR: {TEMPLATES_DIR} <<<\n")


# ============================================================
# SQL (autocontido, estável)
# ============================================================

SQL_AGG = """
WITH filtered AS (
  SELECT
    sr.sensor_id,
    date_trunc('day', sr."date")::date AS day,
    sr.value::double precision AS nh3_value,
    sr.humidity::double precision AS humidity,
    sr.fan_speed::double precision AS fan_speed
  FROM public.sensor_readings sr
  WHERE sr."date" >= :start_date
    AND sr."date" <  :end_date
    AND sr.value IS NOT NULL
    AND sr.value > 0
    AND sr.value < 999
),
daily AS (
  SELECT
    sensor_id,
    day,
    COUNT(*) AS samples,
    AVG(nh3_value) AS nh3_avg,
    MAX(nh3_value) AS nh3_max,
    AVG(humidity) AS humidity_avg,
    AVG(fan_speed) AS fan_speed_avg
  FROM filtered
  GROUP BY sensor_id, day
)
INSERT INTO public.nh3_daily_agg
  (sensor_id, day, samples, nh3_avg, nh3_max, humidity_avg, fan_speed_avg, ct_percent, created_at)
SELECT
  d.sensor_id,
  d.day,
  d.samples,
  d.nh3_avg,
  d.nh3_max,
  d.humidity_avg,
  d.fan_speed_avg,
  CASE
    WHEN d.nh3_avg IS NULL THEN NULL
    ELSE LEAST(100.0, GREATEST(0.0, 100.0 * d.nh3_avg / :ppm_max))
  END AS ct_percent,
  NOW()
FROM daily d
ON CONFLICT (sensor_id, day) DO UPDATE SET
  samples = EXCLUDED.samples,
  nh3_avg = EXCLUDED.nh3_avg,
  nh3_max = EXCLUDED.nh3_max,
  humidity_avg = EXCLUDED.humidity_avg,
  fan_speed_avg = EXCLUDED.fan_speed_avg,
  ct_percent = EXCLUDED.ct_percent,
  created_at = NOW();
"""

SQL_SELECT_DAILY = """
SELECT
  sensor_id,
  day,
  samples,
  nh3_avg,
  nh3_max,
  humidity_avg,
  fan_speed_avg,
  ct_percent
FROM public.nh3_daily_agg
WHERE sensor_id = :sensor_id
  AND day >= :start_day
  AND day <  :end_day
ORDER BY day;
"""


# ============================================================
# Helpers
# ============================================================

def _engine():
    return build_engine(Settings.load())


def _parse_range_inclusive(start_str: str, end_str: str) -> tuple[date, date]:
    """
    Usuário escolhe start/end INCLUSIVOS.
    SQL usa end EXCLUSIVO => end + 1 dia.
    """
    start_day = date.fromisoformat(start_str)
    end_day = date.fromisoformat(end_str)
    return start_day, end_day + timedelta(days=1)


def _load_daily_df(sensor_id: int, start_day: date, end_exclusive: date) -> pd.DataFrame:
    eng = _engine()
    with eng.begin() as conn:
        rows = conn.execute(
            text(SQL_SELECT_DAILY),
            {"sensor_id": sensor_id, "start_day": start_day, "end_day": end_exclusive},
        ).mappings().all()

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df[df["day"].notna()].sort_values("day")

    for col in ["samples", "nh3_avg", "nh3_max", "humidity_avg", "fan_speed_avg", "ct_percent"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _df_to_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    df = df.copy()
    if "day" in df.columns:
        df["day"] = pd.to_datetime(df["day"], errors="coerce")
        df = df[df["day"].notna()].copy()
        df["day"] = df["day"].dt.strftime("%Y-%m-%d")

    return df.to_html(index=False, classes="dbgrid", border=0, justify="left", na_rep="")


def _plotly_line(df: pd.DataFrame, series: list[tuple[str, str]], title: str, y_label: str):
    if go is None:
        raise RuntimeError("Plotly não instalado. Rode: pip install plotly")

    fig = go.Figure()
    for col, name in series:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df["day"], y=df[col], mode="lines", name=name))

    fig.update_layout(
        title=title,
        xaxis_title="Dia",
        yaxis_title=y_label,
        template="plotly_dark",
        height=320,
        margin=dict(l=35, r=20, t=55, b=35),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def _fig_to_html(fig, include_js: bool) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_js else False,
        config={"displaylogo": False, "responsive": True},
    )


# ============================================================
# Routes (UI)
# ============================================================

@router.get("/", response_class=HTMLResponse)
def ui_home(request: Request):
    today = date.today()
    settings = Settings.load()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "start_default": (today - timedelta(days=30)).isoformat(),
            "end_default": today.isoformat(),
            "ppm_max_default": float(getattr(settings, "nh3_ppm_max", 1000.0)),
            "sensor_id_default": 43,
        },
    )


@router.post("/run-aggregate", response_class=HTMLResponse)
def ui_run_aggregate(
    request: Request,
    start: str = Form(...),
    end: str = Form(...),
    ppm_max: float = Form(...),
):
    try:
        start_day, end_exclusive = _parse_range_inclusive(start, end)

        if aggregate_daily is not None:
            aggregate_daily(start_date=start_day, end_date=end_exclusive, ppm_max=float(ppm_max))
        else:
            eng = _engine()
            with eng.begin() as conn:
                conn.execute(
                    text(SQL_AGG),
                    {"start_date": start_day, "end_date": end_exclusive, "ppm_max": float(ppm_max)},
                )

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Agregação concluída",
                "message": f"OK: {start} → {end} (inclusive).",
                "plots": [],
                "table_html": "",
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Agregação (erro)",
                "message": f"{type(e).__name__}: {e}",
                "plots": [],
                "table_html": "",
            },
        )


@router.post("/run-explore", response_class=HTMLResponse)
def ui_run_explore(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    try:
        start_day, end_exclusive = _parse_range_inclusive(start, end)

        df = _load_daily_df(int(sensor_id), start_day, end_exclusive)
        if df.empty:
            return templates.TemplateResponse(
                "result.html",
                {
                    "request": request,
                    "title": "Explore (gráficos)",
                    "message": "Nenhum dado encontrado para esse sensor/período.",
                    "plots": [],
                    "table_html": "",
                },
            )

        plots: list[str] = []

        fig1 = _plotly_line(
            df,
            series=[("nh3_avg", "NH3 médio"), ("nh3_max", "NH3 pico")],
            title="NH3 — Média e Pico Diário",
            y_label="NH3 (ppm)",
        )
        plots.append(_fig_to_html(fig1, include_js=True))

        if "ct_percent" in df.columns:
            fig2 = _plotly_line(df, series=[("ct_percent", "Ct (%)")], title="Ct (%)", y_label="Ct (%)")
            plots.append(_fig_to_html(fig2, include_js=False))

        if "humidity_avg" in df.columns:
            fig3 = _plotly_line(df, series=[("humidity_avg", "Umidade")], title="Umidade", y_label="RH (%)")
            plots.append(_fig_to_html(fig3, include_js=False))

        if "fan_speed_avg" in df.columns:
            fig4 = _plotly_line(df, series=[("fan_speed_avg", "Fan speed")], title="Fan speed", y_label="Fan speed")
            plots.append(_fig_to_html(fig4, include_js=False))

        if "samples" in df.columns:
            fig5 = _plotly_line(df, series=[("samples", "Samples")], title="Samples", y_label="Samples")
            plots.append(_fig_to_html(fig5, include_js=False))

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Explore (gráficos)",
                "message": f"OK: {len(df)} dias (sensor_id={sensor_id}) | {start} → {end}.",
                "plots": plots,
                "table_html": "",
            },
        )

    except Exception as e:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Explore (erro)",
                "message": f"{type(e).__name__}: {e}",
                "plots": [],
                "table_html": "",
            },
        )


@router.post("/show-data", response_class=HTMLResponse)
def ui_show_data(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    try:
        start_day, end_exclusive = _parse_range_inclusive(start, end)
        df = _load_daily_df(int(sensor_id), start_day, end_exclusive)

        if df.empty:
            msg = "Nenhum dado encontrado para esse sensor/período."
            table_html = ""
        else:
            msg = f"OK: {len(df)} linhas (sensor_id={sensor_id}) | {start} → {end}."
            table_html = _df_to_table(df)

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Dados (DBGrid)",
                "message": msg,
                "plots": [],
                "table_html": table_html,
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Dados (erro)",
                "message": f"{type(e).__name__}: {e}",
                "plots": [],
                "table_html": "",
            },
        )


# ============================================================
# Lifetime — agora registrado em /ui/run-lifetime (e alias underscore)
# ============================================================

@router.api_route("/run-lifetime", methods=["GET", "POST"], response_class=HTMLResponse)
@router.api_route("/run_lifetime", methods=["GET", "POST"], response_class=HTMLResponse)  # alias (evita typo)
def ui_run_lifetime(
    request: Request,
    start: str = Form(None),
    end: str = Form(None),
    td_days: float = Form(None),
):
    # GET nunca dá 405
    if request.method == "GET":
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Lifetime diário",
                "message": "Use o formulário na tela inicial para executar (POST).",
                "plots": [],
                "table_html": "",
            },
        )

    try:
        if not start or not end or td_days is None:
            return templates.TemplateResponse(
                "result.html",
                {
                    "request": request,
                    "title": "Lifetime (erro)",
                    "message": "Campos ausentes: start, end, td_days.",
                    "plots": [],
                    "table_html": "",
                },
            )

        if run_lifetime_daily is None or LifetimeParams is None:
            raise RuntimeError("Módulo app.services.lifetime não está disponível/importável no projeto.")

        start_day, end_exclusive = _parse_range_inclusive(start, end)

        # IMPORTANTE: end_exclusive para casar com SQL do tipo day < end
        summary = run_lifetime_daily(
            start_day=start_day,
            end_day=end_exclusive,
            params=LifetimeParams(td_days=float(td_days), eol_percent=30.0),
        )

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Lifetime diário calculado",
                "message": f"OK: {summary}",
                "plots": [],
                "table_html": "",
            },
        )

    except Exception as e:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Lifetime (erro)",
                "message": f"{type(e).__name__}: {e}",
                "plots": [],
                "table_html": "",
            },
        )