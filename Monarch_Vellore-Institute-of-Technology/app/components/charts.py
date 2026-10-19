"""Plotly charts for the pages (dataviz method: one axis, thin 2 px lines, >= 8 px markers, hover on every mark,
legend for 2+ series plus direct labels, recessive grid, status colours only with an icon and a word)."""
from __future__ import annotations

import plotly.graph_objects as go

from components.theme import LEVEL_COLOR, MUTED, SEQ, SERIES, level_icon


def _layout(fig: go.Figure, title: str, y_title: str, x_title: str = "", height: int = 320,
            legend: bool = False) -> go.Figure:
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), height=height,
                      margin=dict(l=10, r=10, t=44, b=10), showlegend=legend, hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1))
    fig.update_xaxes(title_text=x_title, showgrid=False, zeroline=False)
    fig.update_yaxes(title_text=y_title, gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    return fig


def risk_trajectory(dates: list, risk: list, levels: list, title: str, y_title: str,
                    bands: dict | None = None, pct: bool = True) -> go.Figure:
    """One series; each day's marker carries its level colour + icon + word in the tooltip; band lines dashed."""
    y = [100 * r if pct else r for r in risk]
    fig = go.Figure(go.Scatter(
        x=dates, y=y, mode="lines+markers", line=dict(color=SERIES[0], width=2),
        marker=dict(size=10, color=[LEVEL_COLOR.get(lv, MUTED) for lv in levels],
                    line=dict(color="rgba(255,255,255,0.9)", width=2)),
        customdata=[f"{level_icon(lv)} {lv}" for lv in levels],
        hovertemplate="%{x}<br>%{y:.2f}" + ("%" if pct else "") + "<br>level: %{customdata}<extra></extra>"))
    for name, v in (bands or {}).items():
        fig.add_hline(y=100 * v if pct else v, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text=name, annotation_position="top left", annotation_font_size=11)
    return _layout(fig, title, y_title)


def lines(x: list, series: dict[str, list], title: str, y_title: str, x_title: str = "",
          hline: tuple[float, str] | None = None) -> go.Figure:
    """Up to three named series (categorical slots 1-3), legend + direct label at the last point."""
    fig = go.Figure()
    for i, (name, ys) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=x, y=ys, name=name, mode="lines+markers",
                                 line=dict(color=SERIES[i % 3], width=2), marker=dict(size=8),
                                 hovertemplate=f"{name}: %{{y:.3f}}<extra></extra>"))
        last = next((j for j in range(len(ys) - 1, -1, -1) if ys[j] is not None), None)
        if last is not None:
            fig.add_annotation(x=x[last], y=ys[last], text=name, showarrow=False, xanchor="left", xshift=8,
                               font=dict(size=11))
    if hline:
        fig.add_hline(y=hline[0], line=dict(color=MUTED, width=1, dash="dot"), annotation_text=hline[1],
                      annotation_position="top left", annotation_font_size=11)
    return _layout(fig, title, y_title, x_title, legend=len(series) > 1)


def fan(t: list, bands: dict[str, tuple[list, list, list]], title: str, thresholds: dict | None = None) -> go.Figure:
    """Slow-clock ranges: per scenario a 10-90 % band (translucent) and its median line; KDIGO lines dotted."""
    fig = go.Figure()
    for i, (name, (lo, med, hi)) in enumerate(bands.items()):
        c = SERIES[i % 3]
        rgb = tuple(int(c[k:k + 2], 16) for k in (1, 3, 5))
        fig.add_trace(go.Scatter(x=list(t) + list(t)[::-1], y=list(hi) + list(lo)[::-1], fill="toself",
                                 fillcolor=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.14)", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=t, y=med, name=name, mode="lines", line=dict(color=c, width=2),
                                 customdata=list(zip(lo, hi, strict=True)),
                                 hovertemplate=f"{name}<br>year %{{x:.2f}}: median %{{y:.0f}} "
                                               "(10-90 %: %{customdata[0]:.0f}-%{customdata[1]:.0f})<extra></extra>"))
    for name, v in (thresholds or {}).items():
        fig.add_hline(y=v, line=dict(color=MUTED, width=1, dash="dot"), annotation_text=name,
                      annotation_position="bottom left", annotation_font_size=11)
    fig = _layout(fig, title, "eGFR (mL/min/1.73 m²)", "years from now", height=360, legend=True)
    fig.update_layout(hovermode="closest")
    return fig


def bars(labels: list[str], values: list[float], title: str, x_title: str, highlight: str | None = None,
         errors: list[tuple[float, float]] | None = None, text: list[str] | None = None) -> go.Figure:
    """Horizontal bars, one hue (highlighted bar in the darker step), value labels outside the bar end."""
    colors = [SEQ["dark"] if lab == highlight else SEQ["light"] for lab in labels]
    err = None
    if errors:
        err = dict(type="data", symmetric=False, array=[hi - v for v, (_, hi) in zip(values, errors, strict=True)],
                   arrayminus=[v - lo for v, (lo, _) in zip(values, errors, strict=True)], color=MUTED, thickness=1)
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=dict(color=colors, line=dict(width=0)),
                           error_x=err, text=text, textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:.4f}<extra></extra>"))
    fig = _layout(fig, title, "", x_title, height=60 + 34 * len(labels))
    fig.update_layout(hovermode="closest", bargap=0.35)
    fig.update_yaxes(autorange="reversed")
    return fig


def tornado(rows: list[dict], baseline: float, title: str) -> go.Figure:
    """Each parameter's low and high edge as a bar from the baseline (blue = low edge, orange = high edge)."""
    names = [r["parameter"] for r in rows]
    lo = [100 * (r["low"]["risk"] - baseline) for r in rows]
    hi = [100 * (r["high"]["risk"] - baseline) for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=names, x=lo, orientation="h", name="registry low edge", marker_color=SERIES[0],
                         customdata=[r["low"]["value"] for r in rows],
                         hovertemplate="%{y} at %{customdata}: %{x:+.1f} points<extra></extra>"))
    fig.add_trace(go.Bar(y=names, x=hi, orientation="h", name="registry high edge", marker_color=SERIES[1],
                         customdata=[r["high"]["value"] for r in rows],
                         hovertemplate="%{y} at %{customdata}: %{x:+.1f} points<extra></extra>"))
    fig = _layout(fig, title, "", "change in 72-h risk (percentage points)", height=80 + 30 * len(rows), legend=True)
    fig.update_layout(barmode="overlay", hovermode="closest", bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    return fig
