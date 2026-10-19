"""Reusable blocks: the red-flag check-in form (built from config/red_flags.yaml capture_fields, so every sign a flag
uses can be captured), the red-flag result screen, and the audio player for pre-generated speech."""
from __future__ import annotations

import streamlit as st

from vrikka.config import PROJECT_ROOT, load_yaml
from vrikka.i18n import t
from vrikka.voice.nlu import recognise_brands

AUDIO = PROJECT_ROOT / "app" / "assets" / "audio"


def checkin_form(key: str, lang: str, title_key: str = "ui.checkin_title") -> tuple[dict, str] | None:
    """Returns (fields, text) when submitted."""
    cfg = load_yaml("red_flags")
    with st.form(key):
        st.markdown(f"**{t(title_key, lang)}**")
        fields = {}
        cols = st.columns(2)
        for i, f in enumerate(cfg["capture_fields"]):
            label = t(f"capture.{f['name']}", lang)
            with cols[i % 2]:
                if f["type"] == "bool":
                    fields[f["name"]] = st.checkbox(label, key=f"{key}_{f['name']}")
                else:
                    v = st.number_input(label, min_value=0.0, value=None, step=0.5, key=f"{key}_{f['name']}")
                    if v is not None:
                        fields[f["name"]] = float(v)
        text = st.text_area(t("ui.text_checkin", lang), key=f"{key}_text", height=80)
        if st.form_submit_button(t("ui.submit", lang), type="primary"):
            return {k: v for k, v in fields.items() if v not in (False, None)}, text
    return None


def brand_readback(text: str, lang: str) -> None:
    for b in recognise_brands(text or ""):
        st.info(t("ui.medicine_heard", lang, brand=b["brand"].replace("_", "-").title(),
                  generics=" + ".join(b["generics"])))


def screen(res: dict, lang: str) -> None:
    """Show the red-flag outcome: emergency (no risk), urgent (same-day doctor) or none."""
    if res["level"] == "emergency":
        st.error(f"## 🚨 {res['title']}\n\n{res['body']}")
        audio(lang, "redflag_heatstroke_body")
    elif res["level"] == "urgent":
        st.warning(f"### ⚠️ {res['title']}\n\n{res['body']}")
    else:
        st.success(t("ui.no_flags", lang))
    for n in res.get("notes", []):
        st.caption(n)


def audio(lang: str, name: str) -> None:
    f = AUDIO / lang / f"{name}.mp3"
    if f.exists():
        st.audio(str(f), format="audio/mp3")
