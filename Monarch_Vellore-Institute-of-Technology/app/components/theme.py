"""Visual language shared by every page: level badges (icon + word + colour, never colour alone), chart colours (the
validated default palette of the dataviz method: three categorical slots, the fixed status palette, a blue
sequential ramp) and the page frame (language, login, disclaimer)."""
from __future__ import annotations

import streamlit as st

from vrikka.config import load_yaml
from vrikka.i18n import LANGUAGES, is_draft, t

# Fixed status palette for alert levels (never reused for data series); purple = lab-confirmed injury.
LEVEL_COLOR = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b", "purple": "#6250d6", "none": "#8a8984"}
LEVEL_INK = {"green": "#ffffff", "amber": "#1a1a19", "red": "#ffffff", "purple": "#ffffff", "none": "#ffffff"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # categorical slots 1-3 (validated adjacent and all-pairs)
SEQ = {"light": "#86b6ef", "mid": "#2a78d6", "dark": "#184f95"}
MUTED = "#8a8984"

CSS = """
<style>
.vt-badge {display:inline-block;padding:2px 10px;border-radius:12px;font-weight:600;font-size:0.92rem;
           white-space:nowrap;}
.vt-card {border:1px solid rgba(128,128,128,0.25);border-radius:10px;padding:12px 16px;margin:6px 0;}
.vt-muted {opacity:0.75;font-size:0.88rem;}
.vt-hero {font-size:2.2rem;font-weight:700;line-height:1.1;}
.vt-small {font-size:0.82rem;opacity:0.8;}
</style>
"""


def level_icon(level: str) -> str:
    lv = load_yaml("alert_policy")["levels"]
    return lv.get(level, {}).get("icon", "")


def badge(level: str, lang: str = "en") -> str:
    word = t(f"level.{level}", lang) if level in LEVEL_COLOR and level != "none" else level
    return (f'<span class="vt-badge" style="background:{LEVEL_COLOR.get(level, MUTED)};'
            f'color:{LEVEL_INK.get(level, "#fff")}">{level_icon(level)} {word}</span>')


def lang() -> str:
    return st.session_state.get("lang", "en")


def frame(title: str, icon: str = "💧") -> None:
    """Page config, styles, the sidebar (language, login) and the research-prototype notice."""
    st.set_page_config(page_title=f"{title} · VrikkaTwin", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown("### 💧 VrikkaTwin")
        codes = list(LANGUAGES)
        cur = st.session_state.get("lang", "en")
        st.session_state["lang"] = st.selectbox("Language / भाषा / ಭಾಷೆ / భాష", codes, index=codes.index(cur),
                                                format_func=lambda c: LANGUAGES[c], key="lang_select")
        if is_draft(st.session_state["lang"]):
            st.caption("Draft translation, awaiting native-speaker review.")
        from components.api_client import login_box
        login_box()
        st.caption("Research prototype for the Happiest Health Digital Twin Challenge 2026 (Team Monarch, VIT). "
                   "Synthetic data and fictional personas only. Not a medical device.")
    st.title(f"{icon} {title}")
