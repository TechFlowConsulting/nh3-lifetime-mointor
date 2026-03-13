from __future__ import annotations

"""
UI Routes (FastAPI + Jinja2) — NH3 Lifetime Monitor
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import build_engine
from app.services.lifetime import LifetimeParams, run_lifetime_daily

router = APIRouter(tags=["UI"])

# ---------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]  # .../app
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------
# SQLs
# ---------------------------------------------------------------------
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
LEFT JOIN public.nh3_daily_agg e
  ON e.sensor_id = d.sensor_id
 AND e.day      = d.day
WHERE e.sensor_id IS NULL;
"""

SQL_DAILY = """
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

SQL_READ_LIFETIME = """
SELECT
  sensor_id,
  day,
  ct_percent,
  td_days,
  eol_percent,
  b_days,
  lt_days_per_1pct,
  lc_days_per_1pct,
  sa_percent,
  sc_percent,
  dt_days,
  da_days,
  created_at
FROM public.nh3_lifetime_daily
WHERE day >= :start_day
  AND day <  :end_day
ORDER BY sensor_id, day
LIMIT :limit;
"""

SQL_LIFE_DAILY = """
SELECT
  sensor_id,
  day,
  ct_percent,
  td_days,
  eol_percent,
  b_days,
  lt_days_per_1pct,
  lc_days_per_1pct,
  sa_percent,
  sc_percent,
  dt_days,
  da_days
FROM public.nh3_lifetime_daily
WHERE sensor_id = :sensor_id
  AND day >= :start_day
  AND day <  :end_day
ORDER BY day;
"""

# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------
def run_aggregate(start_date: date, end_date: date, ppm_max: float) -> None:
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        conn.execute(
            text(SQL_AGG),
            {"start_date": start_date, "end_date": end_date, "ppm_max": ppm_max},
        )


def load_daily(sensor_id: int, start_day: date, end_day: date) -> pd.DataFrame:
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(SQL_DAILY),
                {"sensor_id": sensor_id, "start_day": start_day, "end_day": end_day},
            )
            .mappings()
            .all()
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.sort_values("day")
    df["day"] = pd.to_datetime(df["day"], errors="coerce")

    for col in [
        "samples",
        "nh3_avg",
        "nh3_max",
        "humidity_avg",
        "fan_speed_avg",
        "ct_percent",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["day"].notna()].copy()
    return df


def load_lifetime(start_day: date, end_day: date, limit: int = 2000) -> pd.DataFrame:
    engine = build_engine(Settings.load())
    with engine.begin() as conn:
        rows = conn.execute(
            text(SQL_READ_LIFETIME),
            {"start_day": start_day, "end_day": end_day, "limit": limit},
        ).mappings().all()

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if "day" in df.columns:
        df["day"] = pd.to_datetime(df["day"], errors="coerce")
        df = df[df["day"].notna()].copy()

    return df


def load_lifetime_daily(sensor_id: int, start_day: date, end_day: date) -> pd.DataFrame:
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(SQL_LIFE_DAILY),
                {"sensor_id": sensor_id, "start_day": start_day, "end_day": end_day},
            )
            .mappings()
            .all()
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df[df["day"].notna()].sort_values("day")

    num_cols = [
        "ct_percent",
        "td_days",
        "eol_percent",
        "b_days",
        "lt_days_per_1pct",
        "lc_days_per_1pct",
        "sa_percent",
        "sc_percent",
        "dt_days",
        "da_days",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df

# ---------------------------------------------------------------------
# Plotly helpers
# ---------------------------------------------------------------------
def _grafana_like_layout(title: str, y_label: str) -> dict[str, Any]:
    return dict(
        title=dict(text=title, x=0.01, xanchor="left"),
        height=320,
        margin=dict(l=55, r=20, t=50, b=45),
        paper_bgcolor="#0b1220",
        plot_bgcolor="#0f172a",
        font=dict(color="#e5e7eb", size=12),
        xaxis=dict(
            title="Dia",
            showgrid=True,
            gridcolor="rgba(148,163,184,0.18)",
            zeroline=False,
            showline=True,
            linecolor="rgba(148,163,184,0.25)",
            ticks="outside",
        ),
        yaxis=dict(
            title=y_label,
            showgrid=True,
            gridcolor="rgba(148,163,184,0.18)",
            zeroline=False,
            showline=True,
            linecolor="rgba(148,163,184,0.25)",
            ticks="outside",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode="x unified",
    )


def fig_to_plotly_html(fig: go.Figure, *, include_js: bool) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_js else False,
        config={
            "displaylogo": False,
            "responsive": True,
            "modeBarButtonsToRemove": [
                "lasso2d",
                "select2d",
                "toggleSpikelines",
                "autoScale2d",
            ],
        },
    )


def build_all_plots_plotly(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    x = df["day"]
    plots: list[str] = []

    # 1) NH3 médio e pico
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=x, y=df["nh3_avg"], mode="lines", name="NH3 médio"))
    fig1.add_trace(go.Scatter(x=x, y=df["nh3_max"], mode="lines", name="NH3 pico"))
    fig1.update_layout(**_grafana_like_layout("NH3 — Média e Pico (por dia)", "NH3 (ppm)"))
    plots.append(fig_to_plotly_html(fig1, include_js=True))

    # 2) Samples
    if "samples" in df.columns:
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(x=x, y=df["samples"], mode="lines", name="Samples"))
        fig5.update_layout(**_grafana_like_layout("Samples por dia (após filtro 0 < NH3 < 999)", "Samples"))
        plots.append(fig_to_plotly_html(fig5, include_js=False))

    # 3) Ct%
    if "ct_percent" in df.columns:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=x, y=df["ct_percent"], mode="lines", name="Ct (%)"))
        layout2 = _grafana_like_layout("Ct% — Concentração média diária normalizada", "Ct (%)")
        layout2["yaxis"] = {**layout2["yaxis"], "range": [0, 100]}
        fig2.update_layout(**layout2)
        plots.append(fig_to_plotly_html(fig2, include_js=False))

    # 4) Umidade
    if "humidity_avg" in df.columns:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=x, y=df["humidity_avg"], mode="lines", name="Umidade"))
        fig3.update_layout(**_grafana_like_layout("Umidade média diária", "RH (%)"))
        plots.append(fig_to_plotly_html(fig3, include_js=False))

    # 5) Fan speed
    if "fan_speed_avg" in df.columns:
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=x, y=df["fan_speed_avg"], mode="lines", name="Fan speed"))
        fig4.update_layout(**_grafana_like_layout("Velocidade média do fan (por dia)", "Fan speed"))
        plots.append(fig_to_plotly_html(fig4, include_js=False))

    return plots


def build_lifetime_plots_plotly(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    x = df["day"]
    plots: list[str] = []

    # 1) Sensibilidade (Sa/Sc)
    fig1 = go.Figure()
    if "sa_percent" in df.columns:
        fig1.add_trace(go.Scatter(x=x, y=df["sa_percent"], mode="lines", name="Sa (%) — sem gás"))
    if "sc_percent" in df.columns:
        fig1.add_trace(go.Scatter(x=x, y=df["sc_percent"], mode="lines", name="Sc (%) — com gás"))
    fig1.update_layout(**_grafana_like_layout("Degradação de sensibilidade (Sa/Sc)", "Sensibilidade (%)"))
    plots.append(fig_to_plotly_html(fig1, include_js=True))

    # 2) Vida restante (Dt/Da)
    fig2 = go.Figure()
    if "dt_days" in df.columns:
        fig2.add_trace(go.Scatter(x=x, y=df["dt_days"], mode="lines", name="Dt (dias) — sem gás"))
    if "da_days" in df.columns:
        fig2.add_trace(go.Scatter(x=x, y=df["da_days"], mode="lines", name="Da (dias) — com gás"))
    fig2.update_layout(**_grafana_like_layout("Vida útil restante estimada (Dt/Da)", "Dias restantes"))
    plots.append(fig_to_plotly_html(fig2, include_js=False))

    return plots

# ---------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------
def df_to_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "<div class='hint'>Nenhum dado encontrado.</div>"

    dfx = df.copy()

    if "day" in dfx.columns:
        dfx["day"] = pd.to_datetime(dfx["day"], errors="coerce").dt.strftime("%Y-%m-%d")

    return dfx.to_html(
        index=False,
        classes="dbgrid",
        border=0,
        justify="center",
        na_rep="",
        escape=False,
    )


def df_to_dbgrid_html(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    dfx = df.copy()

    if "day" in dfx.columns:
        dfx["day"] = pd.to_datetime(dfx["day"], errors="coerce").dt.strftime("%Y-%m-%d")

    return dfx.to_html(
        index=False,
        classes="dbgrid",
        border=0,
        justify="left",
        na_rep="",
    )

# ---------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def ui_home(request: Request):
    today = date.today()
    start_default = today - timedelta(days=30)
    end_default = today + timedelta(days=1)

    settings = Settings.load()
    ppm_max_default = float(getattr(settings, "nh3_ppm_max", 1000.0))

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "start_default": start_default.isoformat(),
            "end_default": end_default.isoformat(),
            "today_default": today.isoformat(),   # <- precisa disso
            "ppm_max_default": ppm_max_default,
            "sensor_id_default": 1,
        },
    )
def ui_home(request: Request):
    today = date.today()
    start_default = today - timedelta(days=90)
    end_default = today + timedelta(days=1)

    settings = Settings.load()
    ppm_max_default = float(getattr(settings, "nh3_ppm_max", 1000.0))

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "start_default": start_default.isoformat(),
            "end_default": end_default.isoformat(),
            "today_default": today.isoformat(),
            "ppm_max_default": ppm_max_default,
            "sensor_id_default": 25,
        },
    )


@router.post("/run-aggregate", response_class=HTMLResponse)
def ui_run_aggregate(
    request: Request,
    start: str = Form(...),
    end: str = Form(...),
    ppm_max: float = Form(...),
):
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    run_aggregate(start_date, end_date, float(ppm_max))

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Agregação concluída",
            "message": f"OK: nh3_daily_agg atualizada para {start_date} -> {end_date} (ppm_max={ppm_max}).",
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
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    df = load_daily(int(sensor_id), start_day, end_day)

    if df.empty:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Explore (gráficos)",
                "message": (
                    "Nenhum dado encontrado em nh3_daily_agg para o sensor e período informados. "
                    "Rode a agregação primeiro e confirme o sensor_id."
                ),
                "plots": [],
                "table_html": "",
            },
        )

    plots_html = build_all_plots_plotly(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Explore (gráficos)",
            "message": f"OK: {len(df)} dias carregados (sensor_id={sensor_id}).",
            "plots": plots_html,
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
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    df = load_daily(int(sensor_id), start_day, end_day)

    if df.empty:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Dados (DBGrid)",
                "message": "Nenhum dado encontrado para o sensor/período informados.",
                "plots": [],
                "table_html": "",
            },
        )

    table_html = df.to_html(index=False, classes="dbgrid", border=0)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Dados (DBGrid)",
            "message": f"OK: {len(df)} linhas carregadas (sensor_id={sensor_id}).",
            "plots": [],
            "table_html": table_html,
        },
    )


@router.post("/run-lifetime", response_class=HTMLResponse)
def ui_run_lifetime(
    request: Request,
    start: str = Form(...),
    end: str = Form(...),
    td_days: float = Form(...),
):
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    summary = run_lifetime_daily(
        start_day=start_day,
        end_day=end_day,
        params=LifetimeParams(td_days=float(td_days), eol_percent=30.0),
    )

    df = load_lifetime(start_day, end_day, limit=2000)
    table_html = df_to_table(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Lifetime diário calculado",
            "message": f"OK: {summary}",
            "plots": [],
            "table_html": table_html,
        },
    )


@router.post("/run-lifetime-explore", response_class=HTMLResponse)
def ui_run_lifetime_explore(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    df = load_lifetime_daily(int(sensor_id), start_day, end_day)

    if df.empty:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Lifetime (degradação)",
                "message": "Nenhum dado encontrado em nh3_lifetime_daily para o sensor/período informados.",
                "plots": [],
                "table_html": "",
            },
        )

    plots_html = build_lifetime_plots_plotly(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Lifetime (degradação)",
            "message": f"OK: {len(df)} dias carregados (sensor_id={sensor_id}).",
            "plots": plots_html,
            "table_html": "",
        },
    )


@router.post("/show-lifetime-data", response_class=HTMLResponse)
def ui_show_lifetime_data(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    df = load_lifetime_daily(int(sensor_id), start_day, end_day)

    if df.empty:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "Lifetime (DBGrid)",
                "message": "Nenhum dado encontrado em nh3_lifetime_daily para o sensor/período informados.",
                "plots": [],
                "table_html": "",
            },
        )

    table_html = df_to_dbgrid_html(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Lifetime (DBGrid)",
            "message": f"OK: {len(df)} linhas carregadas (sensor_id={sensor_id}).",
            "plots": [],
            "table_html": table_html,
        },
    )


@router.post("/agent-explore", response_class=HTMLResponse)
def ui_agent_explore(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    """
    Rota do NHsys IA.
    Recebe o ID do sensor pela interface do agente e abre diretamente
    os gráficos do sensor no período informado.
    """
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    df = load_daily(int(sensor_id), start_day, end_day)

    if df.empty:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "title": "NHsys IA — análise do sensor",
                "message": (
                    f"Não encontrei dados agregados para o sensor {sensor_id} "
                    f"no período de {start} até {end}."
                ),
                "plots": [],
                "table_html": "",
            },
        )

    plots_html = build_all_plots_plotly(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": f"NHsys IA — análise do sensor {sensor_id}",
            "message": (
                f"Oi! Analisei o sensor {sensor_id} no período de {start} até {end}. "
                f"Foram encontrados {len(df)} dias de dados."
            ),
            "plots": plots_html,
            "table_html": "",
        },
    )