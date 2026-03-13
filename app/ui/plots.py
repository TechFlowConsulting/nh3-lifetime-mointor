from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def grafana_line_chart(
    df: pd.DataFrame,
    x: str,
    series: list[tuple[str, str]],
    title: str,
    y_label: str,
):
    fig = go.Figure()

    for col, label in series:
        if col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df[x],
                    y=df[col],
                    name=label,
                    mode="lines",
                    line=dict(width=2),
                    hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.2f}</b><extra>" + label + "</extra>",
                )
            )

    # “Grafana-like”: fundo, grid, tipografia, legenda
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=16)),
        template="plotly_dark",
        height=380,
        margin=dict(l=50, r=20, t=55, b=45),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#111827",
        font=dict(size=12),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#0b1220", font_size=12),
    )

    fig.update_xaxes(
        title="Dia",
        showgrid=True,
        gridcolor="rgba(255,255,255,0.06)",
        zeroline=False,
        showline=True,
        linecolor="rgba(255,255,255,0.12)",
    )

    fig.update_yaxes(
        title=y_label,
        showgrid=True,
        gridcolor="rgba(255,255,255,0.06)",
        zeroline=False,
        showline=True,
        linecolor="rgba(255,255,255,0.12)",
    )

    return fig