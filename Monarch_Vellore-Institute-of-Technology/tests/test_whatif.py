"""What-if levers, sick-day guidance and clinical guardrails (Part 5; master plan §14.2, §38)."""
import json

import pytest

from vrikka.config import CONFIG_DIR, REPORTS_DIR, load_yaml, param
from vrikka.whatif import guardrails as gr
from vrikka.whatif.levers import PatientContext, available_levers, swapped_tablets
from vrikka.whatif.red_flags import LANGUAGES, messages
from vrikka.whatif.sickday import guidance

KAMALA = dict(generics=["telmisartan", "chlorthalidone"], age=68, weight_kg=62, egfr=58,
              painkiller={"combiflam": 3})


# --------------------------------------------------------------------------------------------- guardrails
def test_heart_failure_plus_diuretic_pause_warns():
    assert gr.pause_warnings(["thiazide"], heart_failure=True) == ["guard.hf_diuretic_pause"]
    assert gr.pause_warnings(["loop"], heart_failure=True) == ["guard.hf_diuretic_pause"]
    assert gr.pause_warnings(["thiazide"], heart_failure=False) == []
    assert gr.pause_warnings(["arb"], heart_failure=True) == []
    lv = {r["name"]: r for r in available_levers(PatientContext(**{**KAMALA, "heart_failure": True}))}
    assert "guard.hf_diuretic_pause" in lv["pause_diuretic"]["warning_keys"]
    assert not lv["ors"]["allowed"] and lv["ors"]["blocked_reason_keys"] == ["ors.reason.heart_failure"]


@pytest.mark.parametrize("k, level, actions", [
    (None, None, []), (4.8, None, []), (5.5, "caution", []), (5.9, "caution", []),
    (6.0, "alert", ["same_day_repeat_potassium", "clinician_alert"]),
    (6.8, "alert", ["same_day_repeat_potassium", "clinician_alert"]),
])
def test_potassium_rules(k, level, actions):
    r = gr.potassium_rule(k)
    assert r["level"] == level and r["actions"] == actions
    assert r["caution_on_levers"] == (level is not None)


def test_potassium_caution_reaches_every_lever():
    rows = available_levers(PatientContext(**{**KAMALA, "last_potassium": 6.1}))
    assert rows and all("guard.k_alert" in r["warning_keys"] for r in rows)


def test_paracetamol_ceiling():
    assert gr.paracetamol_ceiling_mg(40, 70) == 1000 * param("paracetamol_ceiling_g_day")
    assert gr.paracetamol_ceiling_mg(68, 62) == 1000 * param("paracetamol_ceiling_high_risk_g_day")
    assert gr.paracetamol_ceiling_mg(40, 45) == 1000 * param("paracetamol_ceiling_high_risk_g_day")
    assert gr.paracetamol_ceiling_mg(40, 70, liver_disease=True) == 1000 * param("paracetamol_ceiling_high_risk_g_day")
    ok = gr.paracetamol_check({"combiflam": 3}, 68, 62)
    assert ok["total_mg"] == 975 and ok["within_ceiling"]
    over = gr.paracetamol_check({"dolo": 4, "combiflam": 3}, 68, 62)       # 2,600 + 975 mg > 3 g
    assert not over["within_ceiling"] and over["message_key"] == "guard.paracetamol_over"


def test_painkiller_swap_counts_paracetamol_in_the_new_tablets():
    assert swapped_tablets(PatientContext(**KAMALA)) == {"dolo": 3}
    lv = {r["name"]: r for r in available_levers(PatientContext(**KAMALA))}
    assert lv["painkiller_swap"]["detail"]["paracetamol"]["total_mg"] == 1950
    assert lv["painkiller_swap"]["warning_keys"] == []
    heavy = PatientContext(**{**KAMALA, "painkiller": {"combiflam": 5}})
    lv = {r["name"]: r for r in available_levers(heavy)}
    assert "guard.paracetamol_over" in lv["painkiller_swap"]["warning_keys"]      # 5 x 650 = 3,250 mg > 3 g


def test_cotrimoxazole_never_suppresses_aki():
    for flag in (True, False):
        r = gr.aki_flag_with_secretion_inhibitor(flag, ["trimethoprim", "sulfamethoxazole"])
        assert r["aki_flag"] is flag and r["note_key"] == "guard.cotrimoxazole" and r["check_potassium"]
    assert gr.aki_flag_with_secretion_inhibitor(True, ["telmisartan"])["note_key"] is None
    brand = load_yaml("drugs_india")["brands"]["septran"]
    assert "never suppress" in brand["note"]


@pytest.mark.parametrize("kw, reasons", [
    (dict(age=17), ["exclude.under_18"]),
    (dict(age=30, pregnant=True), ["exclude.pregnancy"]),
    (dict(age=60, egfr=14.9), ["exclude.egfr_lt_15_or_dialysis"]),
    (dict(age=60, egfr=40, dialysis=True), ["exclude.egfr_lt_15_or_dialysis"]),
    (dict(age=18, egfr=15), []),
])
def test_exclusions(kw, reasons):
    r = gr.exclusion_check(**kw)
    assert r["reason_keys"] == reasons and r["excluded"] == bool(reasons)


# --------------------------------------------------------------------------------------------- levers
def test_levers_come_in_the_agreed_order_and_pauses_carry_the_badge():
    rows = available_levers(PatientContext(**{**KAMALA, "generics": KAMALA["generics"] + ["empagliflozin",
                                                                                         "metformin"]}))
    names = [r["name"] for r in rows]
    assert names[0] == "painkiller_swap" and names[1] == "ors"
    groups = [r["group"] for r in rows]
    assert groups == sorted(groups), "drug pauses come last"
    pauses = [r for r in rows if r["group"] == 3]
    assert {r["name"] for r in pauses} == {"pause_ras", "pause_diuretic", "pause_sglt2i", "pause_metformin"}
    assert all(r["badge_key"] == "lever.badge_pause" for r in pauses)
    reasons = load_yaml("drugs_india")["pause_reason"]
    assert "ketoacidosis" in reasons["sglt2i"] and "lactic acidosis" in reasons["metformin"]
    assert {r["name"]: r["reason_key"] for r in pauses}["pause_sglt2i"] == "pause_reason.sglt2i"


def test_never_levers_are_never_offered():
    never = set(load_yaml("drugs_india")["never_levers"])
    cfg = load_yaml("whatif")["levers"]
    assert not any(set(v.get("applies_if_classes", [])) & never for v in cfg.values())
    rows = available_levers(PatientContext(generics=["metoprolol"], age=60, weight_kg=70, egfr=70))
    assert all(r["group"] < 3 for r in rows)


def test_work_shift_only_for_outdoor_workers():
    assert "work_shift" not in [r["name"] for r in available_levers(PatientContext(**KAMALA))]
    ravi = PatientContext(generics=[], age=42, weight_kg=68, egfr=95, outdoor_hours=9)
    assert [r["name"] for r in available_levers(ravi)] == ["ors", "work_shift"]


@pytest.mark.slow
def test_kamala_levers_reproduce_the_reported_what_if():
    from vrikka.twin.replay import replay
    from vrikka.whatif.levers import run_levers

    cfg = load_yaml("scenarios")["S1_kamala"]
    rep = replay("S1_kamala", cfg, capture_day=8)
    c = rep.context
    rows = run_levers(c["twin"], c["future"], c["baseline_cr"], PatientContext(**KAMALA),
                      selected=["painkiller_swap", "ors", "pause_ras", "pause_diuretic"], seed=c["seed_whatif"])
    got = [round(r["risk"], 3) for r in rows]
    rep_json = json.loads((REPORTS_DIR / "demo_numbers.json").read_text("utf-8"))["scenarios"]["S1_kamala"]
    w = list(rep_json["whatif_72h_risk"].values())
    assert got[0] == w[0] and got[1] == w[1] and got[2] == w[2] and got[-1] == w[3]
    assert rows[0]["text"].startswith(f"{round(100 * w[0])}%")
    assert rows[-1]["text"].startswith("<1%")


# --------------------------------------------------------------------------------------------- sick days / wording
def test_sick_day_guidance_routes_pauses_to_the_clinician():
    g = guidance(["telmisartan", "chlorthalidone", "empagliflozin", "metformin", "amlodipine"],
                 {"fever_excess_c": 1.5})
    assert g["sick_day"]
    keys = {i["generic"]: i for i in g["items"] if i["generic"]}
    assert set(keys) == {"telmisartan", "chlorthalidone", "empagliflozin", "metformin"}
    assert all(i["key"] == "sickday.ask_pause" for i in keys.values())
    assert keys["empagliflozin"]["reason_key"] == "pause_reason.sglt2i"
    assert not guidance(["telmisartan"], {})["sick_day"]


def test_patient_text_never_says_stop_your_medicine():
    for lang in LANGUAGES:
        for k, v in messages(lang).items():
            if k.startswith("_"):
                continue
            text = str(v).lower()
            assert "stop your" not in text and "stop taking" not in text, (lang, k)
    for f in CONFIG_DIR.glob("*.yaml"):
        assert "stop your medicine" not in f.read_text("utf-8").lower(), f.name


def test_every_lever_and_guardrail_key_has_text_in_every_language():
    keys = {v["label_key"] for v in load_yaml("whatif")["levers"].values()} | {"lever.badge_pause", "lever.continue"}
    keys |= {"guard.hf_diuretic_pause", "guard.k_caution", "guard.k_alert", "guard.paracetamol_over",
             "guard.cotrimoxazole", "exclude.under_18", "exclude.pregnancy", "exclude.egfr_lt_15_or_dialysis",
             "sickday.ask_pause", "sickday.painkiller", "sickday.keep_others"}
    keys |= {f"pause_reason.{c}" for c in load_yaml("drugs_india")["pause_reason"]}
    for lang in LANGUAGES:
        missing = keys - set(messages(lang))
        assert not missing, (lang, sorted(missing))
