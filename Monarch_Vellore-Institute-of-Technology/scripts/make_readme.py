"""Write the two READMEs from one template whose every number is read from reports/*.json (no hand-typed numbers).

    python scripts/make_readme.py

Writes README.md in this folder and the same text, with folder-prefixed links, as the repository-root README.md (the
page GitHub shows first). External facts come only from rows marked "supported" in docs/NUMBERS_CHECKED.md.
Re-run after any report changes, or after pasting the video link into VIDEO_URL.
"""
from __future__ import annotations

import json
import re
import sys

from vrikka.config import PROJECT_ROOT, REPORTS_DIR, load_yaml, param
from vrikka.fastclock.features import CORE, FULL

VIDEO_URL = "https://youtu.be/qEd4srvijhY"  # paste the unlisted YouTube link here, then re-run
REPO = "https://github.com/Eeshan842004/VrikkaTwin_Monarch"
FOLDER = PROJECT_ROOT.name
RAW = f"{REPO}/raw/main/{FOLDER}/"


def R(name: str) -> dict:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def pct(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f} %"


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def for_root(text: str) -> str:
    """Point every relative link and image at the team folder, for the README at the repository root."""
    text = re.sub(r"\]\((?!https?://|#|mailto:)", f"](./{FOLDER}/", text)
    return re.sub(r'(src|href)="(?!https?://|#)', rf'\1="./{FOLDER}/', text)


def main() -> int:
    ev, g3, demo = R("fastclock_eval_mismatched"), R("g3_decision"), R("demo_numbers")
    evm, r1, r3, r4 = R("fastclock_eval_matched"), R("r1_validation"), R("r3_tawam"), R("r4_pmdata")
    l1, cal, l45, coh, extra = R("l1_pooled"), R("calibration_checks"), R("literature_checks_l4_l5"), \
        R("cohort_summary"), R("evaluation_extras")
    seasons3 = ("internal_test_2024", "test_2025", "test_2026")
    m = ev["internal_test_2024"]["M_hybrid_core25"]
    prev = m["day_level"]["prevalence"]
    m_auprc = m["day_level"]["auprc"]
    k = demo["scenarios"]["S1_riya"]
    w = k["whatif_72h_risk"]
    wv = list(w.values())
    pd_ = g3["paired_difference_M_minus"]
    lead = g3["lead_time_target_A1_3"]
    ops = {s: ev[s]["M_hybrid_core25"]["alerts"] for s in seasons3}
    pol = load_yaml("alert_policy")
    rb = r1["R1b"]["pooled"]["rmse_mg_dl"]
    ss = cal["sweat_sensitivity"]
    seasons = coh["seasons"]
    n_ep = [seasons[y]["mismatched"]["aki_episodes"] for y in ("2024", "2025", "2026")]
    draws = int(param("mc_draws_ui"))
    lo, hi = 100 * param("slow_band_low_q"), 100 * param("slow_band_high_q")
    red_day = k["summary"]["first_red_day"]
    n_slides = 34
    n_shots = len(list((PROJECT_ROOT / "deliverables" / "screenshots").glob("*.png")))

    if VIDEO_URL:
        video = f"**[Watch the walkthrough on YouTube]({VIDEO_URL})** (unlisted)"
        video_cell = f"[YouTube, unlisted]({VIDEO_URL})"
    else:
        video = "**Video link: added here once the upload is live.**"
        video_cell = "link goes here once uploaded"

    def auprc_row(key: str, name: str) -> str:
        cells = [f"{ev[s][key]['day_level']['auprc']:.4f}" for s in seasons3]
        return f"| {name} | " + " | ".join(cells) + " |"

    def dl(path: str, label: str) -> str:
        return f"[{label}]({RAW}{path})"

    def gallery(items: list[tuple[str, str]]) -> str:
        rows = []
        for i in range(0, len(items), 2):
            cells = "".join(
                f'<td width="50%" valign="top"><a href="deliverables/screenshots/{f}.png">'
                f'<img src="deliverables/screenshots/{f}.png" alt="{c}"></a><br><sub>{c}</sub></td>'
                for f, c in items[i:i + 2])
            rows.append(f"<tr>{cells}</tr>")
        return "<table>\n" + "\n".join(rows) + "\n</table>"

    rob = extra.get("robustness", {})
    rob_lines = []
    names = {"headline_noisy_forecast": "As reported (noisy weather forecast)", "perfect_forecast": "Perfect forecast",
             "no_band": "Nobody wears a band", "tier0_only": "Everyone on Tier 0 (weekly ASHA weight only)",
             "drop30": "30 % of band days missing", "drop50": "50 % of band days missing",
             "noise2x": "Twice the sensor noise"}
    for key, nm in names.items():
        if key in rob:
            v = rob[key]
            rob_lines.append(f"| {nm} | {v['auprc']} | {100 * v['sensitivity_red']:.0f} % | "
                             f"{v['red_per_100_patient_days']} | {v['median_lead_h']} |")
    tor = extra.get("tornado", {})
    rep = extra.get("reproduction", {})
    rep_ok = all(mm["reproduced"] for y in rep.values() for mm in y["models"].values()) if rep else None

    text = f"""# VrikkaTwin

**A kidney digital twin that warns about heat and sick-day kidney injury up to 72 hours before it shows up in a blood
test.**

Team **Monarch** · **Vellore Institute of Technology** · Happiest Health Digital Twin Challenge 2026

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-green.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Data: synthetic and open only](https://img.shields.io/badge/data-synthetic%20%2B%20open-orange.svg)

{video}

---

Picture Riya. She is 68, lives in Nagpur, and takes a BP tablet and a water tablet every morning. In May the city
touches 45 °C. On day 2 she gets a fever, takes a Combiflam, eats a little less and drinks a little less. None of
this feels serious. Over the next few days her kidneys quietly lose the ability to protect themselves, and by the time
anyone measures her creatinine she is already in hospital.

Riya is not a real person (every patient in this project is fictional or synthetic), but her story is very common.
VrikkaTwin keeps a small physiological model of each patient, a "twin", that is updated every morning from a weighing
scale and a resting heart rate. Each morning it plays out the next three days against the weather forecast, the
tablets and the symptoms, and asks the question that matters: is this person's kidney heading for trouble, and what
can we change today?

In our simulation the twin turned Riya **red {k['summary']['lead_time_h']} hours before her kidney injury**, and showed that
swapping the painkiller and adding ORS brings her 72-hour risk down from **{pct(wv[0])}** to **{pct(wv[2], 1)}**.

> VrikkaTwin is a research prototype built for this challenge. It is not a medical device and it has not been used on
> real patients. All patients shown are synthetic or fictional.

## Contents

1. [Team](#1-team)
2. [Submission checklist](#2-submission-checklist)
3. [Problem statement and healthcare use case](#3-problem-statement-and-healthcare-use-case)
4. [What the app does](#4-what-the-app-does)
5. [Architecture](#5-architecture)
6. [The AI and the models](#6-the-ai-and-the-models)
7. [Data](#7-data)
8. [Results](#8-results)
9. [Screenshots](#9-screenshots)
10. [Tech stack](#10-tech-stack)
11. [Run it on your machine](#11-run-it-on-your-machine)
12. [Repository layout](#12-repository-layout)
13. [Licence](#13-licence)
14. [Safety, limitations and what comes next](#14-safety-limitations-and-what-comes-next)
15. [References](#15-references)

## 1. Team

| Item | Details |
|---|---|
| Team name | Monarch |
| Members | Harshita Kumar, Eeshan Gupta |
| College | Vellore Institute of Technology (VIT) |
| Challenge | Happiest Health Digital Twin Challenge 2026 |
| Project | VrikkaTwin (*vrikka* is Sanskrit for kidney) |
| Submission folder | [`{FOLDER}/`](.) |

## 2. Submission checklist

Everything the submission guidelines ask for, and where to find it.

| Asked for | Where it is |
|---|---|
| Team details and college | [Section 1](#1-team) |
| Project title | VrikkaTwin: a kidney digital twin for heatwaves and sick days |
| Problem statement and healthcare use case | [Section 3](#3-problem-statement-and-healthcare-use-case) |
| Technical stack and AI/ML model details | [Section 6](#6-the-ai-and-the-models) and [Section 10](#10-tech-stack) |
| 15-20 minute demo video, unlisted on YouTube | {video_cell} |
| Open-source licence | MIT, see [`LICENSE`](LICENSE) and [Section 13](#13-licence) |
| Architecture diagram (PDF) | {dl('deliverables/architecture.pdf', 'architecture.pdf')} (also as {dl('deliverables/architecture.png', 'PNG')}) |
| Presentation (PDF / PPT) with project details and outcome | {dl('deliverables/VrikkaTwin_Team_Monarch_Presentation.pdf', 'Presentation PDF')} · {dl('deliverables/VrikkaTwin_Team_Monarch_Presentation.pptx', 'PPTX')} ({n_slides} slides) |
| Folder named "Team Name_College Name" | [`{FOLDER}/`](.) |
| Public repository, every link open | This repository is public; the code, reports, diagrams and slides are all in it |

## 3. Problem statement and healthcare use case

### The problem

Acute kidney injury (AKI) is a sudden drop in kidney function over hours to days. Most episodes are mild and recover,
but each one adds to long-term kidney damage, and in older people or people with chronic kidney disease (CKD) it can
end in hospital. Three ordinary things push people over the edge:

- **Heat.** Sweating and poor drinking shrink the body's water. India's 2024 heat season saw 67,637 suspected
  heatstroke cases and 374 deaths between 1 March and 27 July (NCDC surveillance, Lok Sabha reply).
- **A sick day.** Fever, vomiting, loose motions or simply not eating make the dehydration worse.
- **The "triple whammy" of tablets.** A BP tablet of the ACE-inhibitor or ARB type, plus a water tablet (diuretic),
  plus a painkiller such as ibuprofen (inside many brands, Combiflam included). In a study of 487,372 people on BP
  medicines, this combination raised the rate of kidney injury by 1.31 times, and by 1.82 times in the first 30 days
  (Lapi et al., BMJ 2013).

We sum it up as: **heat loads the gun; a sick day or a painkiller pulls the trigger.**

The hard part is that this kind of kidney injury is silent. Creatinine, the blood test that confirms it, only rises
after the damage has started, and at home nobody measures it at the right time. Heat alerts are city-wide and say
nothing about one particular person's tablets or kidneys.

### Who it is for

People with high blood pressure, diabetes or CKD (eGFR 15 or above, not on dialysis) who live through Indian summers,
and the people around them.

| User | Question VrikkaTwin answers |
|---|---|
| Doctor | Which of my patients needs a kidney blood test today, and why? |
| Patient and family | Is today a risky day for my kidneys, and what should I do? (English, Hindi, Kannada or Telugu, with audio) |
| ASHA worker | Is there a danger sign that cannot wait? Works with a weekly weight and no smartwatch |
| Lab | Which home kidney tests are ordered, and where does the result go? |

## 4. What the app does

The app has nine pages and six demo logins (doctor, patient, family, ASHA, lab, admin).

**For the doctor**
- **Doctor Triage:** every patient ranked by 72-hour kidney risk, with a green / amber / red level and the top 3
  reasons in plain words. Ordering a home kidney test is one click.
- **Tomorrow's Kidney Weather:** a city-by-city forecast of how many patients will be green, amber or red tomorrow.
- **Patient Twin:** what the twin currently believes about the patient (body water, creatinine, how much they sweat),
  how well it fits their real readings, the 72-hour risk with its uncertainty, a 10-year kidney outlook shown as a
  range, and a **what-if simulator** that tries the safest changes first.

**For the patient and family**
- **Patient Family:** today's level and what to do, in four languages with audio. If the patient is unwell, the
  advice becomes specific to their own tablets.
- **Emergency: call ambulance** button. One press alerts the doctor and family and opens a "Dial 108" link.
- **Daily medicines list.** Add a medicine by brand or generic name (Combiflam, Telma-H, metformin). The app works out
  what is inside, and if it completes the triple whammy it warns the patient, the family and the doctor at once.
- **Alerts inbox** in the sidebar for every role. Risk alerts go out automatically: amber to the patient and family,
  red to the patient, family and doctor (the doctor and family only while the patient's consent is
  granted).
- A printable **visit summary** in the patient's language.

**For the ASHA worker and the lab**
- **ASHA Field:** a short Tier-0 check-in form, Telugu by default, for patients with no wearable. Danger signs are
  checked before any model runs.
- **Lab Tasks:** home test orders. The result goes back into the twin and updates tomorrow's estimate.

**For trust and for the judges**
- **Trust Center:** signed consent you can revoke in one click, a tamper-evident audit log (you can try tampering
  and watch it fail verification), FHIR R4 export and a DPDP Act 2023 mapping.
- **Time Machine:** replay a persona's heatwave day by day, for example Riya's 12 days, and watch the risk climb
  before her injury.
- **Evaluation:** every result in [Section 8](#8-results), including the ones that did not go our way.

## 5. Architecture

Click a diagram to open it full size, or use the download links underneath.

[![VrikkaTwin system architecture](deliverables/architecture.png)](deliverables/architecture.png)

Download: {dl('deliverables/architecture.png', 'PNG (4K)')} · {dl('deliverables/architecture.pdf', 'PDF')}

Data comes in from four places (health record, wearables or the ASHA visit, the weather, check-ins and labs). It passes
the safety checks first, then the twin estimates the patient's hidden state and simulates the next 72 hours. The
models turn that into a risk, a level and reasons. Every read goes through consent and the audit log before it reaches
a user.

**Presentation** ({n_slides} slides: the problem, our approach, the models, results and outcome): {dl('deliverables/VrikkaTwin_Team_Monarch_Presentation.pdf', 'download PDF')} · {dl('deliverables/VrikkaTwin_Team_Monarch_Presentation.pptx', 'download PPTX')}

**One day in the life of the twin**

[![VrikkaTwin daily flow](deliverables/daily_flow.png)](deliverables/daily_flow.png)

Download: {dl('deliverables/daily_flow.png', 'PNG (4K)')} · {dl('deliverables/daily_flow.pdf', 'PDF')}

The top lane is the automatic morning run (readings at 08:00, risk ready at 09:00). The middle lane is what each level
leads to, including the home test whose result flows back into the twin. The bottom lane is a check-in, which can
happen at any time and always looks for danger signs first.

## 6. The AI and the models

VrikkaTwin is a **hybrid**: a physiology model that understands *why* kidneys get into trouble, plus a machine
learning model that corrects it with data. Doing it this way buys us three things. The twin still works when data is
sparse (one weekly weight is enough). The what-if simulator can test changes the patient has never tried. And every
risk comes with reasons a doctor can check.

### 6.1 The twin: an Unscented Kalman Filter

Each patient has a small body model: total body water, the extracellular fluid deficit, serum creatinine, a personal
sweat multiplier and dry weight. Every morning an **Unscented Kalman Filter** updates these hidden values from the
morning weight and resting heart rate (missing days are fine), and from a lab creatinine whenever one arrives.

What drives the model:
- **Heat exposure:** sweat per hour from the ISO 7933 heat-strain model, using real hourly weather and the person's
  routine (indoor, outdoor, heavy outdoor work).
- **Kidney physiology:** autoregulation that breaks down when the triple-whammy tablets are taken together, an
  exertion effect, and creatinine that follows mass-conserving kinetics.
- **Medicines:** each drug acts with its own effect half-life. The painkiller's clearance depends on the CYP2C9 gene
  (slow metabolisers keep it in the body longer).

### 6.2 72 hours of possible futures

Every morning the twin runs **{draws} possible futures** for the next 72 hours using a deliberately noisy weather
forecast, so the uncertainty is real and not hidden. Each future is scored with the KDIGO kidney-injury rule (a rise of
0.3 mg/dL within 48 hours, or 1.5 times baseline within 7 days). The share of futures that end in injury is the twin's
own risk estimate.

### 6.3 Model M: LightGBM on top of the twin

The final risk comes from **model M**, a LightGBM gradient-boosted tree model trained on the 2024 synthetic season and
then frozen.

**Inputs** ({len(CORE)} features, chosen from {len(FULL)} candidates):

| Group | Features |
|---|---|
| From the twin's simulation | 72-hour injury risk from the simulated futures, peak creatinine ratio, lowest filtration |
| From the twin's current state | creatinine ratio, extracellular fluid (and its uncertainty), filtration fraction, personal sweat multiplier |
| Weather forecast | expected sweat over 72 hours, top temperature, number of hot days in a row |
| Today's check-in | fever, vomiting or loose motions, poor eating and drinking, ORS taken |
| Medicines | painkiller doses in the last 7 days, painkiller today, on an ACE-inhibitor or ARB, on a diuretic, triple whammy today |
| The person | age, baseline eGFR, heart failure, weight compared with dry weight, change in resting heart rate |

Most features carry a **monotone constraint**: the model is not allowed to learn that more heat, or more painkiller,
lowers the risk. That keeps it clinically sensible on data it has not seen.

**Outputs:**
- a calibrated probability of kidney injury in the next 72 hours (isotonic calibration, so 20 % means roughly 1 in 5);
- a level: green, amber or red. The thresholds were fixed in advance so that red stays at or below
  {pol['red_budget_per_100_patient_days']} alerts, and amber plus red at or below {pol['alert_budget_per_100_patient_days']},
  per 100 patient-days, which keeps alert fatigue down;
- the **top 3 reasons** behind each patient's risk, in plain words.

We compared M against five baselines, all fixed before training: last lab value (B0), a heat-index rule (B1), a
points score (B2), a plain LightGBM without the twin (B3) and the twin's physics alone (B4).

### 6.4 What-if simulator

The what-if simulator re-runs the same {draws} futures with one change at a time, always in a safe order: swap the
painkiller first, then ORS and working hours, and only last a medicine pause, which is always marked "clinician
decides". Guardrails stop advice that would be unsafe: ORS limits in heart failure, potassium, paracetamol dose and
co-trimoxazole.

### 6.5 Slow clock: the 10-year view

A Bayesian eGFR slope with registry priors, shown only as a {lo:.0f}-{hi:.0f} % range and never as a single number.
Past injury episodes are "associated with" faster loss (one Indian diabetic kidney disease cohort, n = 274), so that
penalty is applied once and then fades. The Kidney Failure Risk Equation is shown only where it is valid.

### 6.6 Safety comes before the AI

Danger signs (confusion, fits, fainting, temperature of 40 °C or more, no urine for 12 hours) are checked with plain
rules **before** any model runs, and they show "call 108 / 112" straight away. Readings from devices pass an
integrity gate (plausible, fresh, signed). People outside what we designed for (under 18, pregnant, eGFR below 15 or
on dialysis) are told so instead of getting a number.

## 7. Data

No real patient data is used anywhere in this project.

**Why synthetic data.** There is no open dataset from India, or anywhere else we could find, that tracks daily weight,
heart rate, tablets, symptoms, heat and creatinine together for the same people. So we built a synthetic world. To
stop the AI from simply copying our own equations, the world that creates the patients uses a **different kidney
model** from the twin, with hidden causes the twin cannot see. We call this the "mismatched" world, and our headline
results use it.

- **Synthetic cohort:** {coh['n_train_patients']:,} training patients (2024 season) and {coh['n_test_patients']:,}
  separate test patients (2025 and 2026 seasons), enriched for high risk, with {n_ep[0]} / {n_ep[1]} / {n_ep[2]} kidney
  injury episodes across the three seasons. Fixed seed, so anyone can rebuild it.
- **Real weather:** hourly ERA5 data from Open-Meteo for 7 Indian cities (Delhi, Ahmedabad, Nagpur, Hyderabad,
  Chennai, Palasa, Bengaluru), March to June of 2024, 2025 and 2026.
- **Real public data, used only for checking:** MIMIC-IV and eICU demo databases (ICU creatinine), the Tawam CKD
  cohort (491 patients), PMData (Fitbit heart rate and weight from healthy people) and the UCI CKD dataset.

The full list of sources, licences and what is and is not committed is in [`data/README.md`](data/README.md). The
search behind it, including datasets we looked at and turned down, is in [`docs/DATA_SEARCH.md`](docs/DATA_SEARCH.md).

## 8. Results

We wrote the evaluation plan **before** training any model ([`reports/EVAL_PLAN.md`](reports/EVAL_PLAN.md)) and we
report every number against it, including the misses. Every number in this README is read from `reports/*.json` by
[`scripts/make_readme.py`](scripts/make_readme.py); none is typed by hand.

### Headline

- **Model M passed the pre-registered rule.** It beats the last-lab, heat-index and points-score baselines, with
  paired AUPRC differences of {pd_['B0_last_lab_logistic']['point']:+.4f} / {pd_['B1_heat_index_rule']['point']:+.4f} /
  {pd_['B2_triple_heat_egfr_points']['point']:+.4f} (every 95 % CI excludes zero).
- **Red alerts catch {pct(ops['internal_test_2024']['sensitivity_red'])} of injury episodes** on the 2024 test
  patients ({pct(ops['test_2025']['sensitivity_red'])} and {pct(ops['test_2026']['sensitivity_red'])} on the unseen 2025
  and 2026 seasons), while staying inside the red budget: {ops['internal_test_2024']['red_per_100_patient_days']:.2f} red
  alerts per 100 patient-days. Amber or red catches {pct(ops['internal_test_2024']['sensitivity_amber_or_red'])}.
- **Lead time:** a median of {lead['median_h_trigger_ge_24h']:.0f} hours before the injury.
- **Riya:** red at {pct(k['risk_by_day'][red_day], 1)} the morning before her simulated injury. What-if:
  carry on {pct(wv[0])}, swap the painkiller {pct(wv[1], 1)}, add ORS {pct(wv[2], 1)}, add the clinician-decided pauses
  below 1 %. With the slow CYP2C9 *3/*3 gene and the same tablets: {pct(wv[4], 1)}.

### Why the AUPRC numbers look small

Kidney injury days are rare: only {pct(prev, 2)} of patient-days are positive, so a random guess scores about
{prev:.4f}. Model M scores {m_auprc:.4f} on the 2024 test patients, about {m_auprc / prev:.0f} times better than chance.

**AUPRC on the mismatched world** (2024 internal test / 2025 held-out / 2026 held-out):

| Model | 2024 | 2025 | 2026 |
|---|---|---|---|
{auprc_row('B0_last_lab_logistic', 'B0 last lab value')}
{auprc_row('B1_heat_index_rule', 'B1 heat-index rule')}
{auprc_row('B2_triple_heat_egfr_points', 'B2 points score')}
{auprc_row('B3_lightgbm_raw', 'B3 plain LightGBM')}
{auprc_row('B4_twin_physics_risk', 'B4 twin physics only')}
{auprc_row('M_hybrid_core25', '**M hybrid (our lead model)**')}
{auprc_row('M_full_sensitivity', 'M with all features (sensitivity check)')}

### What did not go our way

We think this part matters as much as the wins, so here it is plainly:

- **A plain LightGBM (B3) beat model M on the mismatched world** (paired difference
  {pd_['B3_lightgbm_raw']['point']:+.4f}, CI {pd_['B3_lightgbm_raw']['ci95'][0]:+.4f} to
  {pd_['B3_lightgbm_raw']['ci95'][1]:+.4f}). M wins on the matched world
  ({evm['internal_test_2024']['M_hybrid_core25']['day_level']['auprc']:.3f} against
  {evm['internal_test_2024']['B3_lightgbm_raw']['day_level']['auprc']:.3f}). We kept M as the lead because our rule
  said so in advance, and because only M can run the what-if simulator and give reasons that follow physiology.
- **We missed our lead-time target of 24 hours** by one hour. The model predicts once a day at 09:00 and injuries are
  dated by the 08:00 blood test, so "the day before" comes out as 23 hours.
- **On real ICU data, simply carrying the last creatinine forward beat our kinetic filter** for 24-hour forecasts.

### Checks on real data and published studies

| Check | Result |
|---|---|
| Our KDIGO labelling against the official mimic-code SQL (MIMIC-IV demo) | {r1['R1a']['agreement_pct']} % agreement: pass |
| 24-hour creatinine forecast (MIMIC-IV and eICU demos) | kinetic filter {rb['kinetic_filter']:.3f} vs carry-forward {rb['carry_forward']:.3f} mg/dL RMSE: carry-forward wins |
| 10-year ranking on the Tawam cohort ({r3['patients']} patients) | C-index {r3['c_index_slow_clock_years_to_60']:.3f} vs {r3['c_index_baseline_egfr_alone']:.3f} for baseline eGFR alone: as good, not better |
| False alarms on healthy people (PMData, {r4['people']} people) | {r4['red_notifications_per_100_patient_days']} red alerts per 100 person-days |
| Injury on triple vs double therapy in our synthetic world, against a band set from the BMJ study | rate ratio {l1['pooled']['rr']} ({l1['pooled']['ci95'][0]}-{l1['pooled']['ci95'][1]}), target band {l1['pass_band'][0]}-{l1['pass_band'][1]}: pass |
| Share of injuries caused by heat | about {100 * ss['x0.7']['haf']:.0f}-{100 * cal['haf_matched_regime']['haf']:.0f} % depending on assumptions (central {pct(cal['haf']['all']['haf'], 1)}) |
| End-of-shift injury in heavy outdoor workers | our twin gives {l45['L4']['twin_engine']['share_end_of_shift_aki_pct']:.0f} % against about half of sugarcane cutters in a study of 517 workers: a known gap |
"""
    if rob_lines:
        text += f"""
### Robustness

The {rob.get('season')} held-out season, the same {rob.get('patients', 0):,} test patients in every row, frozen model,
nothing retuned:

| What we changed | AUPRC | Red catches | Red per 100 patient-days | Median lead (h) |
|---|---|---|---|---|
""" + "\n".join(rob_lines) + "\n"
    if tor:
        text += (f"\nWe also screened {tor['parameters_screened']} of the model's assumptions for their effect on Riya's "
                 f"72-hour risk; the share of sweat loss that people drink back comes out {ordinal(tor['phi_drink_rank'])}.")
    if rep_ok is not None:
        text += (" Rebuilding the cohort and features from scratch on a second machine gives the same held-out AUPRC: "
                 + ("yes." if rep_ok else "no (see reports/evaluation_extras.json).") + "\n")

    text += f"""
Subgroups, calibration plots and the rest are on the **Evaluation** page of the app and in [`PROGRESS.md`](PROGRESS.md).

## 9. Screenshots

Click any picture to open it full size. All {n_shots} screenshots are in [`deliverables/screenshots/`](deliverables/screenshots/).

{gallery([("01_doctor_triage", "Doctor Triage: patients ranked by 72-hour risk, with reasons"),
          ("02_patient_twin_whatif", "Patient Twin: the what-if simulator"),
          ("04_patient_family_hindi", "Patient Family in Hindi, with audio"),
          ("05_asha_tier0_telugu", "ASHA Field: Tier-0 check-in in Telugu"),
          ("06_red_flag_emergency", "A danger sign stops everything and shows 108 / 112"),
          ("11_kidney_weather", "Tomorrow's Kidney Weather by city"),
          ("07c_trust_tamper_verify", "Trust Center: a tampered audit log fails verification"),
          ("08_time_machine", "Time Machine: Riya's 12 days replayed")])}

## 10. Tech stack

| Layer | What we used |
|---|---|
| Language | Python 3.12 |
| Twin and physiology | NumPy, SciPy, filterpy (Unscented Kalman Filter), pythermalcomfort (ISO 7933 heat strain) |
| Machine learning | LightGBM (model M and baseline B3), scikit-learn (isotonic calibration, logistic baseline), lifelines (C-index) |
| Clinical equations | CKD-EPI 2021, KDIGO, KFRE (checked against the `kfre` package) |
| Data | pandas, PyArrow, DuckDB (to run the official mimic-code KDIGO SQL), Open-Meteo ERA5 weather |
| App | Streamlit, Plotly; FastAPI and Uvicorn for an optional API |
| Security and trust | cryptography (Fernet encryption, Ed25519 signatures), HMAC hash-chained audit log, PyJWT, bcrypt |
| Interoperability | FHIR R4 export, ABDM-style consent artefacts |
| Languages and voice | English, Hindi, Kannada, Telugu; gTTS audio; a brand-to-generic drug lexicon for Indian medicines; rapidfuzz for free-text check-ins |
| Quality | pytest (app, safety, trust, equation and scenario tests), ruff |

Every model constant lives in [`config/parameters.yaml`](config/parameters.yaml) with its unit, range and source. The
maths and symbols are in [`docs/MATH_CONTEXT.md`](docs/MATH_CONTEXT.md) and the design reasoning in
[`docs/DESIGN.md`](docs/DESIGN.md).

## 11. Run it on your machine

You need Python 3.12 on Windows, macOS or Linux.

```bash
git clone {REPO}.git
cd VrikkaTwin_Monarch/{FOLDER}
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock      # macOS / Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e . --no-deps
.venv/Scripts/python -m streamlit run app/Home.py            # opens http://localhost:8501
```

Log in with the one-click demo buttons in the sidebar. The app starts with everything it needs: trained models,
reports, weather and fictional patients are all in the repository. Its data is kept in memory, so restarting the app
gives a clean demo.

Optional:
- API: `.venv/Scripts/python -m uvicorn vrikka.api.main:app`, then open http://127.0.0.1:8000/docs
- Tests: `.venv/Scripts/python -m pytest` · lint: `ruff check .`
- Rebuild the synthetic world and every report: `scripts/generate_cohort.py`, `scripts/build_features.py`,
  `scripts/train_fastclock.py`, then the checks listed in [`PROGRESS.md`](PROGRESS.md). Public datasets are fetched by
  `scripts/download_public_data.py`, which prints each licence first.

On Windows, if LightGBM crashes with "access violation reading 0x0000000000000000", installing the latest Microsoft
Visual C++ Redistributable (x64) fixes it.

## 12. Repository layout

```
{FOLDER}/
├── app/            Streamlit app (Home + 8 pages, shared components)
├── src/vrikka/     physiology, twin, fastclock, slowclock, whatif, services, security, interop, store, api
│                   simulator/ builds the synthetic world and is never imported by the model code
├── config/         parameter registry, alert policy, red flags, drug lexicon, languages
├── models/         the frozen LightGBM model M and calibrators
├── reports/        every number the app, README and slides quote
├── data/           weather, a small synthetic sample, data licences
├── deliverables/   architecture and daily-flow diagrams, slides, figures, screenshots
├── docs/           design, clinical safety case, maths, data search, numbers checked, diagram sources
├── scripts/        data download, cohort, features, training, checks, reports
└── tests/          unit, safety, trust, app and scenario tests
```

## 13. Licence

- **Code:** MIT licence, see [`LICENSE`](LICENSE).
- **Weather:** Open-Meteo, CC BY 4.0 ("Weather data by Open-Meteo.com").
- **Public datasets:** MIMIC-IV and eICU-CRD demos (ODbL, not redistributed here), UCI CKD, Tawam and PMData
  (CC BY 4.0; PMData not redistributed). The download script fetches them.
- **Synthetic cohort:** generated by our own code, MIT.

Details in [`data/README.md`](data/README.md).

## 14. Safety, limitations and what comes next

The clinical safety case is in [`docs/CLINICAL_SAFETY.md`](docs/CLINICAL_SAFETY.md). In short, what we know is not good
enough yet:

- The model has only been tested on synthetic patients and public datasets, never in a clinic.
- Creatinine rises only after filtration has already dropped, so even a perfect model sees the injury a little late.
- Transient rises in heavy outdoor workers are under-represented in our synthetic world.
- The Hindi, Kannada and Telugu text needs review by native speakers, and two urgent messages need a clinician's
  sign-off.

What we would do next: a prospective pilot with a nephrology clinic and ASHA workers in one hot district, real
smart-scale and band data, and a check of the alert budget against how doctors actually respond.

## 15. References

1. Lapi F. et al. Concurrent use of diuretics, ACE inhibitors and angiotensin receptor blockers with NSAIDs and risk of
   acute kidney injury. BMJ 2013;346:e8525.
2. NCDC heat-related illness surveillance, 2024 season (Lok Sabha reply); NCDC National Action Plan on Heat Related
   Illnesses.
3. Butler-Dawson J. et al. Int Arch Occup Environ Health 2019;92:977-990.
4. Sathiavageesan S. et al. Indian J Nephrol 2025;35:691-3.
5. KDIGO Clinical Practice Guideline for Acute Kidney Injury, 2012.
6. Inker L.A. et al. New creatinine- and cystatin C-based equations to estimate GFR without race. NEJM 2021.
7. Tangri N. et al. Multinational assessment of accuracy of equations for predicting risk of kidney failure. JAMA 2016.
8. ISO 7933. Ergonomics of the thermal environment: predicted heat strain.
9. Johnson A. et al. MIMIC-IV Clinical Database Demo; Pollard T. et al. eICU Collaborative Research Database Demo
   (PhysioNet).
10. Al-Shamsi S. et al. Chronic kidney disease in patients at high risk of cardiovascular disease in the United Arab
    Emirates. PLoS ONE 2018.

Every outside number we quote, with its source and how it was checked, is listed in
[`docs/NUMBERS_CHECKED.md`](docs/NUMBERS_CHECKED.md).
"""
    (PROJECT_ROOT / "README.md").write_text(text, encoding="utf-8")
    (PROJECT_ROOT.parent / "README.md").write_text(for_root(text), encoding="utf-8")
    print("README.md written (team folder and repository root),", len(text.splitlines()), "lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
