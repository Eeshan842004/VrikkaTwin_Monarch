"""Every number the app quotes comes from reports/*.json (working rule: no hand-typed numbers)."""
from __future__ import annotations

import json

import streamlit as st

from vrikka.config import REPORTS_DIR


@st.cache_data(show_spinner=False)
def report(name: str) -> dict:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def pct(x: float | None, digits: int = 0) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def ci_text(ci: list | tuple | None, digits: int = 4, scale: float = 1.0) -> str:
    if not ci:
        return ""
    return f"{ci[0] * scale:.{digits}f}-{ci[1] * scale:.{digits}f}"
