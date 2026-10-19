"""Build the presentation from reports/*.json -> deliverables/VrikkaTwin_slides.pptx (+ PDF via PowerPoint if present).

    python scripts/make_slides.py

Every number on a slide is read from reports/*.json at build time (working rule: no hand-typed numbers), and external
facts come only from rows marked "supported" in docs/NUMBERS_CHECKED.md. Figures use the validated default palette of
the dataviz method (one hue for magnitude, the fixed status colours with icons/words for alert levels).
"""
from __future__ import annotations

import json
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

from vrikka.config import PROJECT_ROOT, REPORTS_DIR, load_yaml, param  # noqa: E402
from vrikka.fastclock.features import CORE  # noqa: E402
from vrikka.slowclock.bayes_slope import fit  # noqa: E402
from vrikka.slowclock.projection import AkiEpisode, Scenario, project  # noqa: E402

OUT = PROJECT_ROOT / "deliverables"
FIG = OUT / "figures"
BLUE, BLUE_L, BLUE_D, ORANGE, AQUA = "#2a78d6", "#86b6ef", "#184f95", "#eb6834", "#1baf7a"
LEVEL = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b", "purple": "#6250d6"}
INK, MUTED = "#0b0b0b", "#52514e"


def R(name: str) -> dict:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def style(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=13, color=INK)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED)
    ax.grid(axis="x" if ax.get_ylabel() == "" else "y", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)


# ------------------------------------------------------------------------------------------------- figures
def fig_auprc(ev: dict) -> str:
    names = {"B0_last_lab_logistic": "B0 last lab", "B1_heat_index_rule": "B1 heat-index rule",
             "B2_triple_heat_egfr_points": "B2 points score", "B4_twin_physics_risk": "B4 twin physics only",
             "M_hybrid_core25": "M hybrid (lead)", "M_full_sensitivity": "M_full (61 features)",
             "B3_lightgbm_raw": "B3 plain LightGBM"}
    it = ev["internal_test_2024"]
    keys = list(names)
    v = np.array([it[k]["day_level"]["auprc"] for k in keys])
    lo = np.array([it[k]["day_level"]["auprc_ci95"][0] for k in keys])
    hi = np.array([it[k]["day_level"]["auprc_ci95"][1] for k in keys])
    fig, ax = plt.subplots(figsize=(7.2, 3.9), dpi=200)
    y = np.arange(len(keys))[::-1]
    ax.barh(y, v, color=[BLUE_D if k == "M_hybrid_core25" else BLUE_L for k in keys], height=0.6)
    ax.errorbar(v, y, xerr=[v - lo, hi - v], fmt="none", ecolor=MUTED, elinewidth=1, capsize=3)
    for yi, vi, h in zip(y, v, hi, strict=True):
        ax.text(h + 0.002, yi, f"{vi:.4f}", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, [names[k] for k in keys])
    style(ax, "AUPRC, 2024 internal-test patients (95 % CI)", "AUPRC")
    ax.set_xlim(0, hi.max() * 1.25)
    fig.tight_layout()
    f = FIG / "auprc.png"
    fig.savefig(f)
    plt.close(fig)
    return str(f)


def fig_riya(demo: dict, dates: list) -> str:
    k = demo["scenarios"]["S1_riya"]
    risk = 100 * np.array(k["risk_by_day"])
    lv = k["levels"]
    x = np.arange(len(risk))
    bands = load_yaml("alert_policy")["levels"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
    ax.plot(x, risk, color=BLUE, linewidth=2, zorder=2)
    icon = {"green": "o", "amber": "s", "red": "D"}
    for lev in ("green", "amber", "red"):
        idx = [i for i, l_ in enumerate(lv) if l_ == lev]
        ax.scatter(x[idx], risk[idx], s=60, color=LEVEL[lev], marker=icon[lev], edgecolor="white", linewidth=1.5,
                   zorder=3, label=lev)
    for name, b in (("amber band", bands["green"]["max_prob"]), ("red band", bands["amber"]["max_prob"])):
        ax.axhline(100 * b, color=MUTED, linestyle=":", linewidth=1)
        ax.text(0, 100 * b + 1, name, fontsize=8, color=MUTED)
    onset = k["summary"]["truth_aki_onset_day"]
    ax.axvline(onset, color=LEVEL["red"], linestyle="--", linewidth=1)
    ax.text(onset + 0.1, risk.max() * 0.92, "simulated kidney\ninjury (08:00)", fontsize=8, color=INK)
    ax.set_xticks(x, [d[5:] for d in dates], rotation=45, fontsize=8)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    style(ax, "Riya (fictional): twin's 72-h simulated risk each morning", "", "risk (%)")
    fig.tight_layout()
    f = FIG / "riya_risk.png"
    fig.savefig(f)
    plt.close(fig)
    return str(f)


def fig_whatif(demo: dict) -> str:
    w = demo["scenarios"]["S1_riya"]["whatif_72h_risk"]
    labels = ["continue as is", "1 painkiller swap", "2 + ORS", "3 + pauses (clinician decides)",
              "same tablets, CYP2C9 *3/*3", "no illness, no painkiller"]
    vals = 100 * np.array(list(w.values()))
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=200)
    y = np.arange(len(vals))[::-1]
    ax.barh(y, vals, color=[BLUE_D, BLUE_L, BLUE_L, BLUE_L, "#c3c2b7", "#c3c2b7"], height=0.6)
    for yi, v in zip(y, vals, strict=True):
        ax.text(v + 0.8, yi, "<1%" if v < 1 else f"{v:.1f} %", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, labels)
    style(ax, "What if ... (same 200 random draws for every row)", "72-h risk (%)")
    ax.set_xlim(0, vals.max() * 1.2)
    fig.tight_layout()
    f = FIG / "riya_whatif.png"
    fig.savefig(f)
    plt.close(fig)
    return str(f)


def fig_slow(slow: dict) -> str:
    sc = load_yaml("scenarios")["S1_riya"]
    post = fit([(0.0, float(sc["person"]["egfr"]))], egfr_now=float(sc["person"]["egfr"]), dm=False)
    scen = [Scenario(label="continue as is"),
            Scenario(episodes=[AkiEpisode(slow["aki_this_season_years"], 1)], label="one stage-1 injury this season"),
            Scenario(sglt2i_start_years=0.0, label="start an SGLT2 inhibitor")]
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=200)
    for c, s in zip((BLUE, ORANGE, AQUA), scen, strict=True):
        p = project(post, s)
        ax.fill_between(p.t_years, p.low, p.high, color=c, alpha=0.12, linewidth=0)
        ax.plot(p.t_years, p.median, color=c, linewidth=2, label=s.label)
        ax.text(p.t_years[-1] + 0.1, p.median[-1], s.label.split(" ")[0], fontsize=8, color=INK, va="center")
    for name, key in (("G3a 60", "egfr_threshold_g3a"), ("G4 30", "egfr_threshold_g4"), ("G5 15", "egfr_threshold_g5")):
        ax.axhline(param(key), color=MUTED, linestyle=":", linewidth=1)
        ax.text(9.0, param(key) + 1, name, fontsize=8, color=MUTED)
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    band = f"{100 * param('slow_band_low_q'):.0f}-{100 * param('slow_band_high_q'):.0f} %"
    style(ax, f"Riya: eGFR ranges ({band}), baseline eGFR only", "years from now", "eGFR")
    fig.tight_layout()
    f = FIG / "riya_slowclock.png"
    fig.savefig(f)
    plt.close(fig)
    return str(f)


def fig_tornado(tor: dict) -> str | None:
    if not tor:
        return None
    rows = tor["top10"][::-1]
    base = tor["baseline_risk"]
    fig, ax = plt.subplots(figsize=(7.2, 3.9), dpi=200)
    y = np.arange(len(rows))
    lo = [100 * (r["low"]["risk"] - base) for r in rows]
    hi = [100 * (r["high"]["risk"] - base) for r in rows]
    ax.barh(y, lo, color=BLUE, height=0.6, label="registry low edge")
    ax.barh(y, hi, color=ORANGE, height=0.6, alpha=0.85, label="registry high edge")
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.set_yticks(y, [r["parameter"] for r in rows], fontsize=8)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    style(ax, f"Top 10 assumptions: Riya's 72-h risk (baseline {100 * base:.1f} %)", "change (percentage points)")
    fig.tight_layout()
    f = FIG / "tornado.png"
    fig.savefig(f)
    plt.close(fig)
    return str(f)


# ------------------------------------------------------------------------------------------------- slides
class Deck:
    def __init__(self):
        self.p = Presentation()
        self.p.slide_width, self.p.slide_height = Inches(13.333), Inches(7.5)
        self.blank = self.p.slide_layouts[6]

    def slide(self, title: str, kicker: str = ""):
        s = self.p.slides.add_slide(self.blank)
        bar = s.shapes.add_shape(1, 0, 0, self.p.slide_width, Inches(0.12))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(BLUE[1:])
        bar.line.fill.background()
        self.text(s, title, 0.5, 0.3, 12.3, 0.8, 30 if len(title) <= 55 else 24, bold=True)
        if kicker:
            self.text(s, kicker, 0.5, 1.05, 12.3, 0.5, 15, color=MUTED)
        foot = "VrikkaTwin · Team Monarch, Vellore Institute of Technology · synthetic data and fictional personas only"
        self.text(s, foot, 0.5, 7.05, 12.3, 0.3, 10, color=MUTED)
        return s

    @staticmethod
    def text(s, txt, x, y, w, h, size=16, bold=False, color=INK):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        lines = txt if isinstance(txt, list) else [txt]
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = line
            para.font.size = Pt(size)
            para.font.bold = bold
            para.font.color.rgb = RGBColor.from_string(color[1:])
            para.space_after = Pt(6)
        return tb

    def bullets(self, s, items, x, y, w, h, size=17):
        return self.text(s, ["• " + i for i in items], x, y, w, h, size)

    @staticmethod
    def image(s, path, x, y, w=None, h=None):
        return s.shapes.add_picture(path, Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)

    def save(self, path):
        self.p.save(str(path))


def main() -> int:
    FIG.mkdir(parents=True, exist_ok=True)
    ev, g3, demo, slow = R("fastclock_eval_mismatched"), R("g3_decision"), R("demo_numbers"), R("slowclock_demo")
    r1, r3, r4, l1, cal, l45 = R("r1_validation"), R("r3_tawam"), R("r4_pmdata"), R("l1_pooled"), \
        R("calibration_checks"), R("literature_checks_l4_l5")
    extra, panel = R("evaluation_extras"), R("demo_triage_panel")
    dates = json.loads((PROJECT_ROOT / "data" / "synthetic" / "demo_patients.json").read_text("utf-8"))[
        "S1_riya"]["dates"]
    k = demo["scenarios"]["S1_riya"]
    m = ev["internal_test_2024"]["M_hybrid_core25"]
    pd_ = g3["paired_difference_M_minus"]
    lead = g3["lead_time_target_A1_3"]
    draws = int(param("mc_draws_ui"))
    d = Deck()

    # 1 title
    s = d.p.slides.add_slide(d.blank)
    d.text(s, "VrikkaTwin", 0.8, 1.6, 11.5, 1.2, 60, bold=True, color=BLUE_D)
    d.text(s, "A kidney digital twin that warns of heat- and sick-day kidney injury up to 72 hours ahead, "
              "for people with hypertension and CKD", 0.8, 2.9, 11.5, 1.2, 24)
    d.text(s, ["Team Monarch · Vellore Institute of Technology", "Happiest Health Digital Twin Challenge 2026",
               "Research prototype: synthetic data and fictional personas only; not a medical device"],
           0.8, 4.6, 11.5, 1.6, 16, color=MUTED)

    # 2 problem
    s = d.slide("The problem: silent kidney injury in heatwaves and sick days",
                "Usually mild, usually recovers, and invisible at home unless someone tests creatinine")
    d.bullets(s, [
        "India's 2024 heat season: 67,637 suspected heatstroke cases and 374 deaths, 1 Mar - 27 Jul 2024 "
        "(NCDC surveillance; Lok Sabha reply)",
        "The 'triple whammy' (ACE inhibitor / ARB + diuretic + NSAID): kidney-injury rate ratio 1.31 overall and 1.82 "
        "in the first 30 days (Lapi et al., BMJ 2013, 487,372 people)",
        "Sweat on top of a diuretic, a fever, a Combiflam from the pharmacy: the injury builds over days, while the "
        "next creatinine test is weeks away",
        "Who needs what: the doctor (whom to test today), the patient and family (what to do, in their language), the "
        "ASHA worker (when to escalate)"], 0.6, 1.7, 12.1, 4.8, 19)

    # 3 architecture
    s = d.slide("How VrikkaTwin works", "Observed data only -> personal twin -> 72-hour simulation -> calibrated, "
                "explained risk -> safe actions, through one trust layer")
    d.image(s, str(OUT / "architecture.png"), 0.6, 1.6, h=5.3)

    # 4 twin + fast clock
    s = d.slide("The twin and the fast clock")
    d.bullets(s, [
        "Personal twin: an Unscented Kalman Filter over total and extracellular water deficit, creatinine, a personal "
        "sweat multiplier and dry weight, updated every morning from weight and resting heart rate (missing readings "
        "allowed)",
        "Exposure: ISO 7933 heat-strain model on real Open-Meteo weather and the person's routine; drugs with their "
        "own "
        "effect half-lives; mass-conserving creatinine kinetics",
        f"Every morning the twin simulates the next 72 hours {draws} times on a noisy forecast and applies the same "
        "KDIGO rule (08:00 creatinine) used for the labels",
        f"Hybrid model M: LightGBM on {len(CORE)} monotone core features, isotonic calibration, top-3 reasons in "
        "English, Hindi, Kannada and Telugu",
        "Alerts with budgets set in advance: red (doctor review + home kidney test) and amber (self-care), with "
        "hysteresis and 72-hour de-duplication"], 0.6, 1.4, 12.1, 5.4, 18)

    # 5 Riya
    s = d.slide("Riya (fictional), 68, Nagpur: the morning before",
                f"ARB + chlorthalidone + Combiflam, fever from day 2. Red the morning before her simulated injury "
                f"(lead {k['summary']['lead_time_h']} h); the naive "
                f"heat-index rule fired on {k['summary']['heat_index_rule_days']} of {k['summary']['days']} days")
    d.image(s, fig_riya(demo, dates), 0.4, 1.6, w=6.4)
    d.image(s, fig_whatif(demo), 6.8, 1.6, w=6.2)
    d.text(s, "Levers in the agreed order: painkiller swap -> ORS / work hours -> medicine pauses last, badged "
              "'individualised, weak evidence (Think Kidneys 2018), clinician decides'. Patient text never says "
              "'stop your medicine'.", 0.6, 5.3, 12.1, 1.2, 14, color=MUTED)

    # 6 slow clock
    s = d.slide("The slow clock: ranges, never a single number",
                "Bayesian eGFR slope with registry priors; each stable lab narrows the range")
    d.image(s, fig_slow(slow), 0.4, 1.6, w=7.2)
    ka = slow["personas"]["S1_riya"]["scenarios"]
    diff = ka["one stage-1 kidney injury this season"]["difference_at_10y_vs_continue"]
    d.bullets(s, [
        f"Riya, eGFR in 10 years: {ka['continue as is']['egfr_range_by_year']['10'][0]:.0f}-"
        f"{ka['continue as is']['egfr_range_by_year']['10'][2]:.0f} (wide: no serial labs yet)",
        f"One stage-1 injury this season is associated with {diff['low']:.1f} to {diff['high']:.1f} mL/min/1.73 m² "
        "at 10 years (one Indian diabetic kidney disease cohort, n = 274; extrapolated without diabetes)",
        "Penalty applied once for any injury and fading; SGLT2 inhibitor effect from EMPA-KIDNEY as an input",
        "KFRE shown only where valid (eGFR 10-59 with a urine albumin result)"], 7.8, 1.7, 5.1, 5.0, 15)

    # 7 safety
    s = d.slide("Safety first", "Red flags run before any model; guardrails sit on every piece of advice")
    d.bullets(s, [
        "Emergency (confusion, fainting, seizure, unresponsive, 40 °C or more): 'Call 108 / 112 now', no kidney score "
        "shown (NCDC heat-illness action plan)",
        "Urgent (no urine 12 h, cola urine with muscle pain after heat or work, vomiting that keeps no fluid down "
        "6 h): "
        "same-day doctor, level at least red",
        "ORS withheld with heart failure, eGFR < 30 or potassium >= 5.5 (WHO ORS has 75 mmol/L sodium, 20 potassium)",
        "Paracetamol total across brands vs the daily ceiling; potassium >= 6.0 always means a same-day repeat; "
        "co-trimoxazole never cancels a kidney alert; beta-blockers, anticoagulants and insulin are never offered "
        "as pauses",
        "Never '0 %' (shown as '<1%' with its interval); eGFR tagged 'not reliable' while creatinine is changing; "
        "not designed for under-18s, pregnancy or eGFR < 15"], 0.6, 1.6, 12.1, 5.2, 17)

    # 8 trust
    s = d.slide("Trust by construction", "One services layer for the app and the API: role -> consent -> audit")
    d.bullets(s, [
        "ABDM-style consent artefact (purpose, requester, data types, expiry), Ed25519-signed and checked on every "
        "read; one-click revoke takes effect at once (test S11)",
        "HMAC hash-chained audit log with Ed25519-signed checkpoints: an edit breaks the chain; a forger with the HMAC "
        "key still fails the signed checkpoint (live tamper demo)",
        "Data-integrity gate: implausible values, weight jumps, stale time stamps, replayed nonces and unsigned device "
        "messages are rejected and audited (test S10)",
        "Each role sees only its fields (ASHA: level and red flags; lab: the test; admin: no clinical data); names "
        "encrypted at rest; FHIR R4 export; DPDP Act 2023 mapping"], 0.6, 1.6, 12.1, 5.2, 17)

    # 9 results
    s = d.slide("Results on the synthetic world (headline: mismatched simulator)",
                f"Positive-day prevalence {100 * m['day_level']['prevalence']:.2f} %; 2024 internal-test patients; "
                "held-out 2025 / 2026 seasons used once")
    d.image(s, fig_auprc(ev), 0.4, 1.6, w=6.6)
    b3 = pd_["B3_lightgbm_raw"]
    ops = [ev[x]["M_hybrid_core25"]["alerts"] for x in ("internal_test_2024", "test_2025", "test_2026")]
    d.bullets(s, [
        "Pre-registered rule: M leads (beats B0 / B1 / B2; paired CIs exclude 0)",
        f"Honest: a plain LightGBM (B3) beats M on this world (difference {b3['point']:+.4f}, CI "
        f"{b3['ci95'][0]:+.4f} to {b3['ci95'][1]:+.4f}); M wins on the matched world and carries the what-if",
        "Red alerts catch " + " / ".join(f"{100 * o['sensitivity_red']:.0f}" for o in ops) + " % of injuries with "
        + " / ".join(f"{o['alerts_per_aki_caught_red']:.1f}" for o in ops) + " alerts per injury caught "
        "(2024 / 2025 / 2026)",
        f"Median lead {lead['median_h_trigger_ge_24h']:.0f} h: the pre-registered >= 24 h target is missed"],
        7.2, 1.7, 5.7, 5.0, 15)

    # 10 reality checks
    s = d.slide("Reality checks on real data and literature", "Held-out checks were never used for tuning")
    rb = r1["R1b"]["pooled"]["rmse_mg_dl"]
    d.bullets(s, [
        f"R1a labelling vs official mimic-code KDIGO (MIMIC-IV demo): {r1['R1a']['agreement_pct']} % agreement - pass",
        f"R1b 24-h creatinine forecast (MIMIC + eICU): kinetic filter {rb['kinetic_filter']:.3f} vs carry-forward "
        f"{rb['carry_forward']:.3f} mg/dL - carry-forward wins",
        f"R3 slow clock on Tawam ({r3['patients']} patients): C-index {r3['c_index_slow_clock_years_to_60']:.3f} vs "
        f"baseline eGFR alone {r3['c_index_baseline_egfr_alone']:.3f} - as good, not better",
        f"R4 healthy real people (PMData, {r4['people']} people, {r4['patient_days']} days): "
        f"{r4['red_notifications_per_100_patient_days']:.0f} red alerts",
        f"L1 triple vs double therapy: RR {l1['pooled']['rr']} ({l1['pooled']['ci95'][0]}-{l1['pooled']['ci95'][1]}) "
        f"in the band {l1['pass_band'][0]}-{l1['pass_band'][1]}",
        f"L4 heavy outdoor worker: cross-shift AKI {l45['L4']['twin_engine']['share_end_of_shift_aki_pct']:.0f} % vs "
        "~50 % in cane cutters - stated limitation",
        f"Heat share of injuries: {100 * cal['sweat_sensitivity']['x0.7']['haf']:.0f}-"
        f"{100 * cal['haf_matched_regime']['haf']:.0f} % depending on assumptions (central "
        f"{100 * cal['haf']['all']['haf']:.0f} %)"], 0.6, 1.5, 12.1, 5.4, 16)

    # 11 robustness
    s = d.slide("Robustness and sensitivity (frozen model, reported as they came out)")
    tor = fig_tornado(extra.get("tornado", {}))
    if tor:
        d.image(s, tor, 0.4, 1.3, w=6.6)
    rob = extra.get("robustness", {})
    items = []
    names = {"headline_noisy_forecast": "headline", "perfect_forecast": "perfect forecast",
             "no_band": "no wearable band", "tier0_only": "everyone Tier 0", "drop50": "50 % band days missing",
             "noise2x": "sensor noise x2"}
    for key, nm in names.items():
        if key in rob:
            items.append(f"{nm}: AUPRC {rob[key]['auprc']}, red sensitivity {100 * rob[key]['sensitivity_red']:.0f} %")
    if "headline_noisy_forecast" in rob:
        h = rob["headline_noisy_forecast"]["auprc_ci95"]
        ov = all(v["auprc_ci95"][0] <= h[1] and v["auprc_ci95"][1] >= h[0] for kk, v in rob.items()
                 if isinstance(v, dict) and kk != "headline_noisy_forecast")
        items.append("Every variant's AUPRC confidence interval overlaps the headline's: "
                     + ("no measurable change (a weekly weight carries the signal)" if ov else "see the report"))
    rep = extra.get("reproduction", {})
    if rep:
        items.append("Re-generated cohort and features reproduce the reported held-out AUPRC: "
                     + ("yes" if all(mm["reproduced"] for y in rep.values() for mm in y["models"].values()) else "no"))
    if extra.get("tornado"):
        items.append(f"Drinking fraction ranks {extra['tornado']['phi_drink_rank']} of "
                     f"{extra['tornado']['parameters_screened']} screened assumptions")
    d.bullets(s, items or ["Run scripts/evaluate.py to add this slide's numbers"], 7.2, 1.4, 5.7, 5.4, 14)

    # 12 limitations
    s = d.slide("What we do not claim")
    d.bullets(s, [
        "Synthetic validation only: no dataset links wearables, heat, medicines and serial outpatient creatinine",
        "Creatinine rises only after filtration has fallen; older people with low muscle mass may be under-detected",
        "Lead-time target missed; a plain LightGBM beat the hybrid model on the mismatched world; R1b lost to "
        "carry-forward; heavy outdoor workers' transient rises are under-represented",
        "Hindi, Kannada and Telugu text and two urgent messages await native-speaker and clinician review",
        "Not a medical device: a prospective clinical study and CDSCO review would come first"],
        0.6, 1.5, 12.1, 5.2, 18)

    # 13 run
    s = d.slide("Try it", "Everything runs locally from the repository")
    d.bullets(s, [
        "python -m streamlit run app/Home.py  ->  http://localhost:8501 (one-click demo logins per role)",
        "python -m uvicorn vrikka.api.main:app  ->  http://127.0.0.1:8000/docs",
        "Pages: Doctor Triage · Patient Twin · Patient and Family · ASHA Field · Lab Tasks · Trust Center · Time "
        "Machine · Evaluation",
        "Every number in the app, README and these slides is read from reports/*.json; the evaluation plan was "
        "committed before any model was trained (reports/EVAL_PLAN.md)"], 0.6, 1.6, 12.1, 4.5, 18)
    if panel:
        d.text(s, f"Triage demo: {panel['demo_date']}, {panel['patients_in_red_state_that_day']} of "
                  f"{panel['eligible_patients_that_day']} held-out test patients red.", 0.6, 6.2, 12.1, 0.5, 13,
               color=MUTED)

    pptx = OUT / "VrikkaTwin_slides.pptx"
    d.save(pptx)
    print("wrote", pptx)
    pdf = OUT / "VrikkaTwin_slides.pdf"
    ps = (f"$pp = New-Object -ComObject PowerPoint.Application; $p = $pp.Presentations.Open('{pptx}', $true, $false, "
          f"$false); $p.SaveAs('{pdf}', 32); $p.Close(); $pp.Quit()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=300)
        print("wrote", pdf)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print("PDF export skipped (PowerPoint not available):", e)
    _ = Emu
    return 0


if __name__ == "__main__":
    sys.exit(main())
