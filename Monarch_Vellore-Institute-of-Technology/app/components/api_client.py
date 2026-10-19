"""The app's only door to the backend: one in-process services layer (role + consent + audit) per server process.

Demo logins are one click, but they still go through the real login (bcrypt + signed token + audit entry).
"""
from __future__ import annotations

import streamlit as st

from vrikka.config import settings
from vrikka.security.auth import DEMO_USERS, Session
from vrikka.services import Services

ROLE_LABEL = {"doctor": "Doctor", "patient": "Patient (Riya, fictional)", "family": "Family (Riya's family)",
              "asha": "ASHA worker", "lab": "Lab / home test", "admin": "Admin (trust only)"}


@st.cache_resource(show_spinner="Starting the services layer ...")
def services() -> Services:
    return Services()


def _password(role: str) -> str:
    return getattr(settings(), f"demo_{role}_password")


def session() -> Session | None:
    return st.session_state.get("session")


def login_as(username: str) -> Session | None:
    role = DEMO_USERS[username][0]
    s = services().login(username, _password(role))
    st.session_state["session"] = s
    return s


def login_box() -> None:
    s = session()
    if s is not None:
        st.success(f"Logged in: **{ROLE_LABEL[s.role]}**")
        if st.button("Log out", key="logout"):
            st.session_state.pop("session", None)
            st.rerun()
        return
    st.markdown("**Demo login** (one click; passwords from `.env`)")
    for user, (role, _) in DEMO_USERS.items():
        if st.button(ROLE_LABEL[role], key=f"login_{user}", width="stretch"):
            login_as(user)
            st.rerun()


def require(*roles: str) -> Session:
    """Stop the page unless someone with one of these roles is logged in (offer quick logins otherwise)."""
    s = session()
    if s is not None and s.role in roles:
        return s
    who = ", ".join(ROLE_LABEL[r] for r in roles)
    st.info(f"This page is for: **{who}**. Use a demo login in the sidebar"
            + (f" (you are logged in as {ROLE_LABEL[s.role]})." if s else "."))
    cols = st.columns(len(roles))
    for c, r in zip(cols, roles, strict=True):
        user = next(u for u, (role, _) in DEMO_USERS.items() if role == r)
        if c.button(f"Log in as {ROLE_LABEL[r]}", key=f"req_{r}"):
            login_as(user)
            st.rerun()
    st.stop()
