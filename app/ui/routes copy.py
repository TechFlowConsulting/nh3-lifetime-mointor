from __future__ import annotations

"""
UI Routes (FastAPI + Jinja2) — NH3 Lifetime Monitor
---------------------------------------------------

Este módulo entrega:
- Página principal /ui (formulários)
- POST /ui/run-aggregate   -> executa agregação diária no banco
- POST /ui/run-explore     -> carrega agregados e gera gráficos

Versão Plotly (interativo):
- Os gráficos são retornados como HTML (div + JS do Plotly)
- Para não duplicar JS, incluímos PlotlyJS apenas no primeiro gráfico

Observação:
- NÃO coloque inicializações pesadas no topo (DB, loops, etc.)
- Aqui DB só é acessado dentro das funções (por requisição).
"""

import io
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

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse
from datetime import date
from app.services.lifetime import LifetimeParams, run_lifetime_daily


router = APIRouter(tags=["UI"])

# ---------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]  # .../app
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------
# SQLs (mantidos como strings para simplificar e evitar I/O no import)
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
ON CONFLICT (sensor_id, day) DO UPDATE SET
  samples = EXCLUDED.samples,
  nh3_avg = EXCLUDED.nh3_avg,
  nh3_max = EXCLUDED.nh3_max,
  humidity_avg = EXCLUDED.humidity_avg,
  fan_speed_avg = EXCLUDED.fan_speed_avg,
  ct_percent = EXCLUDED.ct_percent,
  created_at = NOW();
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
  sensor_id, day,
  ct_percent, td_days, eol_percent,
  b_days, lt_days_per_1pct, lc_days_per_1pct,
  sa_percent, sc_percent,
  dt_days, da_days,
  created_at
FROM public.nh3_lifetime_daily
WHERE day >= :start_day
  AND day <  :end_day
ORDER BY sensor_id, day
LIMIT :limit;
"""
# ---------------------------------------------------------------------
# DB helpers (executam somente durante request)
# ---------------------------------------------------------------------
def run_aggregate(start_date: date, end_date: date, ppm_max: float) -> None:
    """
    Executa agregação diária no banco (UPSERT em nh3_daily_agg).
    """
    settings = Settings.load()
    engine = build_engine(settings)

    with engine.begin() as conn:
        conn.execute(
            text(SQL_AGG),
            {"start_date": start_date, "end_date": end_date, "ppm_max": ppm_max},
        )

def load_daily(sensor_id: int, start_day: date, end_day: date) -> pd.DataFrame:
    """
    Carrega dados diários agregados (nh3_daily_agg) para um sensor e período.
    """
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

    # Normalizações defensivas
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

# ---------------------------------------------------------------------
# Plotly helpers (Grafana-like)
# ---------------------------------------------------------------------
def _grafana_like_layout(title: str, y_label: str) -> dict[str, Any]:
    """
    Define um layout escuro com grid suave, semelhante ao Grafana.
    """
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
    """
    Converte um Figure em HTML. Para evitar duplicar JS:
    - include_js=True somente no primeiro gráfico
    - include_js=False nos demais
    """
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
def load_lifetime(start_day: date, end_day: date, limit: int = 2000) -> pd.DataFrame:
    engine = build_engine(Settings.load())
    with engine.begin() as conn:
        rows = conn.execute(
            text(SQL_READ_LIFETIME),
            {"start_day": start_day, "end_day": end_day, "limit": limit},
        ).mappings().all()
    return pd.DataFrame(rows)

def build_all_plots_plotly(df: pd.DataFrame) -> list[str]:
    """
    Gera uma lista de gráficos Plotly em HTML (list[str]).
    """
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
     
     # 5) Samples
    if "samples" in df.columns:
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(x=x, y=df["samples"], mode="lines", name="Samples"))
        fig5.update_layout(**_grafana_like_layout("Samples por dia (após filtro 0 < NH3 < 999)", "Samples"))
        plots.append(fig_to_plotly_html(fig5, include_js=False))

    # 2) Ct%
    if "ct_percent" in df.columns:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=x, y=df["ct_percent"], mode="lines", name="Ct (%)"))
        layout2 = _grafana_like_layout("Ct% — Concentração média diária normalizada", "Ct (%)")
        # Estilo painel para percentual
        layout2["yaxis"] = {**layout2["yaxis"], "range": [0, 100]}
        fig2.update_layout(**layout2)
        plots.append(fig_to_plotly_html(fig2, include_js=False))
    

    # 3) Umidade
    if "humidity_avg" in df.columns:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=x, y=df["humidity_avg"], mode="lines", name="Umidade"))
        fig3.update_layout(**_grafana_like_layout("Umidade média diária", "RH (%)"))
        plots.append(fig_to_plotly_html(fig3, include_js=False))

    # 4) Fan speed
    if "fan_speed_avg" in df.columns:
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=x, y=df["fan_speed_avg"], mode="lines", name="Fan speed"))
        fig4.update_layout(**_grafana_like_layout("Velocidade média do fan (por dia)", "Fan speed"))
        plots.append(fig_to_plotly_html(fig4, include_js=False))

   

    return plots
def df_to_table(df: pd.DataFrame) -> str:
    """
    Converte DataFrame em tabela HTML (DBGrid simples).
    """
    if df is None or df.empty:
        return "<div class='hint'>Nenhum dado encontrado.</div>"

    df = df.copy()

    # Formata datas se existir coluna day
    if "day" in df.columns:
        df["day"] = pd.to_datetime(df["day"], errors="coerce").dt.strftime("%Y-%m-%d")

    return df.to_html(
        index=False,
        classes="dbgrid",
        border=0,
        justify="center",
        na_rep="",
        escape=False,
    )
# ---------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def ui_home(request: Request):
    """
    Página principal da UI.
    """
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
            "ppm_max_default": ppm_max_default,
            "sensor_id_default": 1,
        },
    )

@router.post("/run-aggregate", response_class=HTMLResponse)
def ui_run_aggregate(
    request: Request,
    start: str = Form(...),
    end: str = Form(...),
    ppm_max: float = Form(...),
):
    """
    Executa agregação diária no banco.
    """
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
        },
    )

@router.post("/run-explore", response_class=HTMLResponse)
def ui_run_explore(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    """
    Carrega agregados diários e gera gráficos interativos Plotly.
    """
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
            },
        )

    plots_html = build_all_plots_plotly(df)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "title": "Explore (gráficos)",
            "message": f"OK: {len(df)} dias carregados (sensor_id={sensor_id}).",
            "plots": plots_html,  # list[str] (HTML)
        },
    )
@router.post("/show-data", response_class=HTMLResponse)
def ui_show_data(
    request: Request,
    sensor_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    """
    Mostra os dados agregados (nh3_daily_agg) em formato de tabela (DBGrid).
    """
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
    """
    Rota para executar o lifetime diário e mostrar o resumo na UI.
    """

@router.post("/run-lifetime", response_class=HTMLResponse)
def ui_run_lifetime(
    request: Request,
    start: str = Form(...),
    end: str = Form(...),
    td_days: float = Form(...),
):
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)

    # 1) calcula e grava
    summary = run_lifetime_daily(
        start_day=start_day,
        end_day=end_day,
        params=LifetimeParams(td_days=float(td_days), eol_percent=30.0),
    )

    # 2) carrega do banco para exibir
    df = load_lifetime(start_day, end_day, limit=2000)

    # 3) converte para HTML (DBGrid)
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