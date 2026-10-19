"""Screenshots of the running app for the slides -> deliverables/screenshots/*.png (Playwright, system Chrome).

    python -m streamlit run app/Home.py      # in another terminal (http://localhost:8501)
    python scripts/take_screenshots.py

Each shot logs in with the one-click demo login, acts like a user (language switch, check-in, consent revoke, tamper
demo) and saves a 1600-px-wide PNG. The last step presses "Reset the demo" so the server returns to its start state.
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import Page, sync_playwright

from vrikka.config import PROJECT_ROOT

BASE = "http://localhost:8501"
OUT = PROJECT_ROOT / "deliverables" / "screenshots"
W, H = 1600, 1000


def ready(page: Page, extra: float = 2.0) -> None:
    page.wait_for_selector('[data-testid="stSidebar"]', timeout=180_000)
    t0 = time.time()
    while time.time() - t0 < 3 and page.locator('[data-testid="stStatusWidget"]').count() == 0:
        time.sleep(0.2)                                   # give a just-triggered rerun time to start
    t0 = time.time()
    while time.time() - t0 < 300 and page.locator('[data-testid="stStatusWidget"]').count() > 0:
        time.sleep(0.5)                                   # then wait until it has finished
    time.sleep(extra)


def open_page(page: Page, path: str, login: str | None = None) -> None:
    page.goto(f"{BASE}/{path}", wait_until="networkidle", timeout=180_000)
    ready(page)
    if login:
        page.locator('[data-testid="stSidebar"] button', has_text=login).first.click()
        page.wait_for_selector("text=Logged in", timeout=300_000)
        ready(page, 3.0)


def shot(page: Page, name: str, anchor: str | None = None, full: bool = False) -> None:
    if anchor:
        page.get_by_text(anchor, exact=False).first.scroll_into_view_if_needed()
        time.sleep(1.0)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name, flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": W, "height": H})

        open_page(page, "Doctor_Triage", "Doctor")
        shot(page, "11_kidney_weather")
        shot(page, "01_doctor_triage", anchor="Synthetic panel scored by model M")

        open_page(page, "Patient_Twin", "Patient (Riya, fictional)")
        shot(page, "02_patient_twin_whatif", anchor="What if")
        shot(page, "03_slow_clock", anchor="Slow clock: long-term eGFR ranges")
        shot(page, "10_twin_knows_patient", anchor="How well does the twin know this patient?")

        open_page(page, "Patient_Family", "Patient (Riya, fictional)")
        page.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"]').first.click()
        page.get_by_role("option", name="हिन्दी").click()
        ready(page, 3.0)
        shot(page, "04_patient_family_hindi")

        open_page(page, "ASHA_Field", "ASHA worker")
        shot(page, "05_asha_tier0_telugu", anchor="ASHA Field")
        page.locator("textarea").first.fill("స్పృహ లేదు, చాలా వేడిగా ఉంది")
        page.get_by_role("button", name="పంపండి").click()
        ready(page, 3.0)
        shot(page, "06_red_flag_emergency", anchor="108")

        open_page(page, "Time_Machine")
        shot(page, "08_time_machine", full=True)
        open_page(page, "Evaluation")
        shot(page, "09_evaluation_reality_checks", full=True)

        # consent revoke (patient) -> audit + tamper demo (admin); done last because revoking changes server state
        open_page(page, "Patient_Family", "Patient (Riya, fictional)")
        page.get_by_role("button", name="Stop sharing").first.click()
        ready(page, 3.0)
        shot(page, "07a_trust_consent_revoked", anchor="Who can see your kidney information")
        open_page(page, "Trust_Center", "Admin (trust only)")
        page.get_by_role("tab", name="Audit log").click()
        ready(page, 2.0)
        shot(page, "07b_trust_audit_log")
        page.get_by_role("tab", name="Tamper demo").click()
        page.get_by_role("button", name="Run the tamper demo").click()
        ready(page, 3.0)
        shot(page, "07c_trust_tamper_verify")
        page.get_by_role("tab", name="Who sees what").click()
        page.get_by_role("button", name="Reset the demo").click()
        ready(page, 3.0)

        # one-click visit summary (Hindi), rendered from the same services the app uses
        sys.path.insert(0, str(PROJECT_ROOT / "app"))
        from components.summary import visit_summary_html

        from vrikka.services import Services
        sv = Services()
        rec = sv.read_patient(sv.login("riya", "patient-demo"), "S1_riya")
        page.set_viewport_size({"width": W, "height": H})
        page.set_content(visit_summary_html(rec, "hi"))
        time.sleep(1.0)
        shot(page, "12_visit_summary_hindi", full=True)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
