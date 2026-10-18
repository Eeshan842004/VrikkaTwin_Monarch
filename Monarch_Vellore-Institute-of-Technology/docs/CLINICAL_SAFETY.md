# Clinical safety case

VrikkaTwin is a research prototype built for the Happiest Health Digital Twin Challenge 2026. It has been tested only on
synthetic patients and on small open datasets. **It is not a medical device and must not be used to make decisions
about real patients** without prospective clinical validation and regulatory review (in India, CDSCO rules for
software as a medical device). This document lists what the software does to stay safe, what it cannot do, and which
test checks each rule. Every number here comes from a file in `reports/`, which is named next to it.

## 1. Intended use

- **Who:** adults with hypertension and/or chronic kidney disease (CKD G1-G4), at home, during a heat season or a
  sick day (fever, vomiting, diarrhoea, a new painkiller).
- **What it gives:** a 72-hour estimate of kidney-injury risk (fast clock), a long-term eGFR range (slow clock), and
  what-if comparisons of safer choices. A red level means "this person should have a creatinine test and a painkiller
  review", not a diagnosis.
- **Who acts on it:** a doctor (red), the patient or family (amber self-care), an ASHA worker (screening). Medicine
  changes are always the clinician's decision.

## 2. People it is not designed for (`whatif/guardrails.exclusion_check`, `config/guardrails.yaml`)

| Exclusion | Why | Test |
|---|---|---|
| Age under 18 | Equations and cohort are adult-only | `test_whatif.py::test_exclusions` |
| Pregnancy | Physiology (GFR, volume) differs; not modelled | same |
| eGFR below 15 or on dialysis | Outside the kidney model and the label definition | same |

When an exclusion applies, no risk is computed and the screen says why.

## 3. Red flags run before any model (`whatif/red_flags.py`, `config/red_flags.yaml`)

| Level | Signs | What happens | Source |
|---|---|---|---|
| Emergency | confusion, fainting, seizure, unresponsive, or temperature 40 °C or higher | "Call 108 / 112 now" screen; **no kidney risk is computed or shown** | NCDC National Action Plan on Heat Related Illnesses |
| Urgent | no urine for 12 h; cola-coloured urine with muscle pain after heat or heavy work | same-day doctor message; level is at least red | team wording, `clinical_wording: VERIFY` |
| Urgent | vomiting that stops fluids staying down for more than 6 h | same-day doctor message; level is at least red | team wording, `clinical_wording: VERIFY` |

- A text check-in ("peshab nahi") without a duration is treated as meeting the duration rule, and the screen says so.
- Every fired flag is written to the HMAC hash-chained audit log.
- **Open item:** a clinician must sign off the two URGENT messages, and native speakers must review the Hindi, Kannada
  and Telugu text (all marked "draft translation").
- Tests: `test_safety.py` (all flags in all four languages, emergency suppresses the risk model, text check-in).

## 4. Guardrails on advice and what-if levers (`whatif/guardrails.py`, `config/guardrails.yaml`)

| Guardrail | Rule | Test |
|---|---|---|
| ORS | With heart failure, eGFR below 30 or last potassium 5.5 or higher, the ORS lever and "drink ORS" advice become "Fluid type and amount as advised by your doctor" (WHO ORS carries 75 mmol/L sodium and 20 mmol/L potassium) | `test_safety.py::test_ors_guardrail` |
| Paracetamol ceiling | Daily total across brands (Combiflam carries 325 mg) against 4 g/day, or 3 g/day at age 65 or over, weight under 50 kg, liver disease or alcohol use (registry, VERIFY) | `test_whatif.py::test_paracetamol_ceiling` |
| Potassium | 6.0 mmol/L or higher: always a same-day repeat and a clinician alert; 5.5 or higher: caution on every lever | `test_whatif.py::test_potassium_rules` |
| Heart failure + diuretic pause | The pause lever carries a fluid-overload warning; clinician decides | `test_whatif.py::test_heart_failure_plus_diuretic_pause_warns` |
| Co-trimoxazole / trimethoprim | Raises creatinine by blocking secretion but can also cause real AKI and high potassium: **an AKI flag is never suppressed**; potassium check advised | `test_whatif.py::test_cotrimoxazole_never_suppresses_aki` |
| Never-levers | Beta-blockers, antiplatelets, anticoagulants, insulin and antiepileptics are never offered as pause levers | `test_whatif.py::test_never_levers_are_never_offered` |

### What-if lever order (`config/whatif.yaml`)
1. Painkiller swap (ibuprofen / diclofenac to paracetamol, checked against the ceiling).
2. ORS / fluids (within the ORS guardrail) and, for outdoor workers, moving work to the early morning.
3. Drug pauses **last**, each with the badge "Individualised, weak evidence (Think Kidneys 2018), clinician decides".
   The SGLT2 inhibitor pause reason is ketoacidosis risk (not kidney injury); the metformin pause reason is lactic
   acidosis if kidney injury develops.

Patient-facing text never says "stop your medicine": it says "ask your doctor today whether to pause ..."
(`test_whatif.py::test_patient_text_never_says_stop_your_medicine`).

## 5. Display rules (`fastclock/display.py`, `config/guardrails.yaml`)

- A risk is never shown as "0 %": below 1 % it reads "<1%", and every Monte-Carlo risk carries its 95 % Wilson interval
  (200 draws cannot resolve less than 0.5 %).
- A lab eGFR taken while creatinine is changing (0.3 mg/dL or more from the last stable value) is tagged "Not reliable
  while creatinine is changing" and is not used by the slow clock.
- The twin shows "modelled filtration (% of personal baseline, twin estimate)", not an eGFR.
- Every level has an icon, a word and a colour (never colour alone).
- Slow-clock outputs are 10-90 % ranges, never a single "kidney-years" number. The AKI slope penalty is "associated
  with" (one Indian diabetic kidney disease cohort, n = 274) and "extrapolated" for people without diabetes.
- Episodes are called "kidney injury (usually mild, usually recovers)", never "kidney failure".

## 6. Known limitations (stated, not hidden)

1. **Synthetic validation only.** All fast-clock performance numbers come from a simulated, enriched high-risk cohort
   (`reports/fastclock_eval_mismatched.json`). The "mismatched" world deliberately uses different equations from the
   twin, but it is still a simulation.
2. **Creatinine lags filtration by 24-48 hours.** A creatinine-defined label and a creatinine-driven twin cannot see an
   injury before creatinine moves; the red alert is a prompt to test, not a measurement of injury.
3. **Lead time target missed.** Median lead time of red alerts is 23 h (red at 09:00 the day before an 08:00 onset);
   the pre-registered target of at least 24 h was not met (`reports/g3_decision.json`).
4. **A plain LightGBM beat the hybrid model on the mismatched world** (internal-test AUPRC in
   `reports/g3_decision.json`); the hybrid model leads by the pre-registered rule and is needed for the what-if.
5. **Older people.** Low muscle mass can blunt creatinine rises, so creatinine-defined kidney injury may be
   under-detected at age 75 or over (subgroup results in `reports/fastclock_eval_mismatched.json`).
6. **Dehydration-only ceiling.** In the twin a healthy kidney on no drugs loses at most 1 - a_tot of its filtration to
   dehydration (20 % when young), so dehydration alone cannot cause kidney injury in that person; severe heat illness
   is covered by the red flags, not by the model (`docs/MATH_CONTEXT.md`).
7. **Heavy outdoor workers (L4).** The engine under-represents transient cross-shift creatinine rises: 0 % cross-shift
   AKI against about 50 % in cane cutters, even after the engine revision (`reports/literature_checks_l4_l5.json`).
8. **Kinetic creatinine filter (R1b).** On real ICU data, carrying the last value forward beat our filter 24 h ahead
   (`reports/r1_validation.json`).
9. **Slow clock (R3).** On the Tawam cohort the slow clock ranks progression to eGFR < 60 about as well as baseline
   eGFR alone, not better (`reports/r3_tawam.json`); without serial eGFR values its ranges are wide.
10. **Heat share is a range.** The heat-attributable fraction depends on assumptions and is always quoted as a range
    (`reports/calibration_checks.json`).
11. **Drug lexicon and translations** need pharmacist and native-speaker review (`config/drugs_india.yaml`,
    `config/i18n/*.yaml`).

## 7. Hazard log

| Hazard | Cause | Control | Verified by |
|---|---|---|---|
| Heatstroke missed while a kidney score is shown | Model runs on an emergency | Red flags run first; emergency suppresses the risk | `test_emergency_runs_before_and_suppresses_the_risk_model` |
| Fluid overload from ORS | Heart failure, low eGFR, high potassium | ORS guardrail | `test_ors_guardrail` |
| Paracetamol overdose after a painkiller swap | Several brands contain paracetamol | Total across brands vs ceiling | `test_painkiller_swap_counts_paracetamol_in_the_new_tablets` |
| Hyperkalaemia missed | Lever advice ignores potassium | K rules on every lever | `test_potassium_caution_reaches_every_lever` |
| Real AKI explained away | Co-trimoxazole raises creatinine | Flag never suppressed | `test_cotrimoxazole_never_suppresses_aki` |
| Patient stops a vital medicine | Wording | Pauses routed to the clinician; never-levers | `test_patient_text_never_says_stop_your_medicine`, `test_never_levers_are_never_offered` |
| False reassurance from "0 %" | Monte-Carlo resolution | "<1%" floor + interval | `test_risk_is_never_shown_as_zero_percent` |
| Wrong eGFR during AKI | CKD-EPI assumes steady state | "Not reliable" tag; slow clock skips it | `test_lab_egfr_tagged_while_creatinine_is_changing`, `test_values_taken_while_creatinine_is_changing_are_skipped` |
| Use outside the intended population | Children, pregnancy, dialysis | Exclusion check | `test_exclusions` |
| Tampered records | Audit log edited | HMAC hash chain + signed checkpoints | `test_audit_log_detects_tampering` (Part 6 adds checkpoint tests) |
