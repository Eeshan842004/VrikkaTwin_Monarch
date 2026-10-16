"""Medical-safety layer (Decisions v4 4b, 4d, 5a-5c; v5 C3, C4): red flags before any risk model, ORS guardrails,
eGFR-during-AKI tagging, risk display rules, the audit log they write to, and wording rules."""
import re

import pytest

from vrikka.config import CONFIG_DIR, load_yaml, param, registry
from vrikka.fastclock.display import lab_egfr_status, modelled_filtration, risk_text, wilson_interval
from vrikka.security.audit import AuditLog
from vrikka.whatif.guardrails import ors_guardrail
from vrikka.whatif.red_flags import LANGUAGES, evaluate, messages, parse_text, screen_then_risk

SCRIPT = {"hi": r"[ऀ-ॿ]", "kn": r"[ಀ-೿]", "te": r"[ఀ-౿]"}
EMERGENCY = [{"confusion": True}, {"fainting": True}, {"seizure": True}, {"unresponsive": True},
             {"temperature_c": 40.0}, {"temperature_c": 41.2}]
URGENT_KIDNEY = [{"no_urine_hours": 12}, {"dark_cola_urine": True, "muscle_pain": True,
                                         "after_heat_or_heavy_work": True}]
URGENT_VOMIT = [{"vomiting_cannot_keep_fluids_hours": 7}]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_each_flag_shows_the_right_screen_in_every_language_and_is_audited(lang):
    log = AuditLog(key="test-key")
    cases = [(c, "emergency", "heatstroke_emergency") for c in EMERGENCY] + \
            [(c, "urgent", "kidney_test_today") for c in URGENT_KIDNEY] + \
            [(c, "urgent", "vomiting_review_today") for c in URGENT_VOMIT]
    msg = messages(lang)
    for checkin, level, flag in cases:
        r = evaluate(checkin, lang, audit=log, patient_id="P1")
        assert r.level == level and flag in r.flags, (checkin, r)
        key = load_yaml("red_flags")["flags"][flag]["message_key"]
        assert r.title == msg[f"{key}.title"] and r.body == msg[f"{key}.body"]
        if lang in SCRIPT:
            assert re.search(SCRIPT[lang], r.body), f"{lang} message is not in {lang} script"
        if level == "emergency":
            assert not r.show_risk and "108" in r.body and "112" in r.body
    assert len(log.records) == len(cases)
    assert all(rec["action"] == "red_flag" and rec["subject"] == "P1" for rec in log.records)
    assert log.verify()


def test_no_flag_below_the_thresholds():
    for checkin in ({}, {"temperature_c": 39.9}, {"no_urine_hours": 11}, {"vomiting_cannot_keep_fluids_hours": 6 - 1},
                    {"dark_cola_urine": True, "muscle_pain": True}, {"muscle_pain": True}):
        assert evaluate(checkin).level == "none", checkin


def test_emergency_runs_before_and_suppresses_the_risk_model():
    called = []
    out = screen_then_risk({"seizure": True}, lambda: called.append(1) or 0.3)
    assert out["risk"] is None and not called
    out = screen_then_risk({"no_urine_hours": 14}, lambda: 0.02)
    assert out["risk"] == 0.02 and out["minimum_level"] == "red"
    out = screen_then_risk({}, lambda: 0.02)
    assert out["minimum_level"] is None


def test_emergency_wins_over_urgent():
    r = evaluate({"confusion": True, "no_urine_hours": 20})
    assert r.level == "emergency" and set(r.flags) == {"heatstroke_emergency", "kidney_test_today"}


@pytest.mark.parametrize("text, lang, level", [
    ("she is confused and very hot", "en", "emergency"),
    ("temp 104 F since morning", "en", "emergency"),
    ("bukhar 40.5 C hai", "hi", "emergency"),
    ("दादी बेहोश हो गईं", "hi", "emergency"),
    ("ಪ್ರಜ್ಞೆ ತಪ್ಪಿತು", "kn", "emergency"),
    ("స్పృహ లేదు", "te", "emergency"),
    ("no urine for 14 hours", "en", "urgent"),
    ("पेशाब नहीं", "hi", "urgent"),                       # no duration stated -> treated as urgent, noted
    ("నీళ్లు తాగినా వాంతి", "te", "urgent"),
    ("bukhar 38.5 C, thoda chakkar", "hi", "none"),
    ("mild headache", "en", "none"),
])
def test_text_check_in_captures_red_flags(text, lang, level):
    checkin = parse_text(text, lang)
    r = evaluate(checkin, lang)
    assert r.level == level, (text, checkin, r)


def test_stated_sign_without_duration_is_flagged_and_says_so():
    r = evaluate(parse_text("peshab nahi", "hi"), "hi")
    assert r.level == "urgent" and r.duration_assumed == ["no_urine_hours"]
    assert r.notes == [messages("hi")["redflag.duration_not_stated"]]


def test_cola_urine_needs_muscle_pain_and_heat_or_work_context():
    base = parse_text("cola coloured urine and muscle pain", "en")
    assert evaluate(base).level == "none"
    assert evaluate({**base, "after_heat_or_heavy_work": True}).level == "urgent"


def test_every_flag_sign_can_be_captured_in_the_forms_and_the_lexicon():
    cfg = load_yaml("red_flags")
    fields = {f["name"] for f in cfg["capture_fields"]}
    for f in cfg["flags"].values():
        for sign in f["any_of"]:
            spec = cfg["signs"].get(sign)
            if spec is None:
                need = {sign}
            else:
                need = set(spec.get("all_of", [])) | ({spec["field"]} if "field" in spec else set())
            assert need <= fields, (sign, need - fields)
    lex = load_yaml("symptoms_lexicon")
    for sign in ("confusion", "fainting", "seizure", "unresponsive", "no_urine", "dark_cola_urine", "muscle_pain",
                 "cannot_keep_fluids"):
        assert set(LANGUAGES) <= set(lex[sign]), sign


def test_i18n_files_have_the_same_keys_and_mark_draft_translations():
    keys = {lang: set(messages(lang)) for lang in LANGUAGES}
    assert all(k == keys["en"] for k in keys.values()), {lang: keys["en"] ^ k for lang, k in keys.items()}
    for lang in ("hi", "kn", "te"):
        assert messages(lang)["_meta"]["status"] == "draft translation"


# --------------------------------------------------------------------------------------------- ORS guardrails
@pytest.mark.parametrize("hf, egfr, k, allowed, reasons", [
    (False, 58.0, 4.6, True, []),
    (True, 58.0, 4.6, False, ["ors.reason.heart_failure"]),
    (False, 29.9, None, False, ["ors.reason.egfr_lt_30"]),
    (False, 30.0, None, True, []),
    (False, 45.0, 5.5, False, ["ors.reason.k_ge_5_5"]),
    (True, 25.0, 6.1, False, ["ors.reason.heart_failure", "ors.reason.egfr_lt_30", "ors.reason.k_ge_5_5"]),
    (False, None, None, True, []),
])
def test_ors_guardrail(hf, egfr, k, allowed, reasons):
    g = ors_guardrail(hf, egfr, k)
    assert g["ors_lever_allowed"] is allowed and g["reason_keys"] == reasons
    assert g["advice_key"] == ("ors.drink" if allowed else "ors.doctor_advises")
    assert g["badge_key"] == ("ors.evidence" if allowed else "ors.caution")
    assert messages("en")["ors.doctor_advises"] == "Fluid type and amount as advised by your doctor."


def test_who_ors_composition_is_recorded():
    who = load_yaml("guardrails")["ors"]["who_reduced_osmolarity_ors"]
    assert (who["sodium_mmol"], who["potassium_mmol"], who["total_osmolarity_mosm"]) == (75, 20, 245)


# --------------------------------------------------------------------------------------------- display rules
def test_risk_is_never_shown_as_zero_percent():
    for p in (0.0, 0.001, 0.004, 0.0099):
        assert risk_text(p)["text"] == "<1%"
        assert risk_text(p, 200)["text"].startswith("<1%")
    assert not any(risk_text(p / 1000, 200)["text"].startswith("0%") for p in range(0, 1000))
    assert risk_text(0.45, 200)["text"].startswith("45% (95% interval")


def test_monte_carlo_interval_brackets_the_estimate():
    for p in (0.0, 0.05, 0.45, 1.0):
        lo, hi = wilson_interval(p, 200)
        assert 0 <= lo <= p <= hi <= 1
    assert wilson_interval(0.0, 200)[1] > 0.005, "200 draws cannot resolve below 0.5 %"


def test_lab_egfr_tagged_while_creatinine_is_changing():
    assert lab_egfr_status(1.0, 1.0)["reliable"]
    assert not lab_egfr_status(1.35, 1.0)["reliable"]
    assert lab_egfr_status(1.35, 1.0)["tag_key"] == "egfr.not_reliable"
    assert not lab_egfr_status(1.1, 1.0, twin_aki_flag=True)["use_in_slow_clock"]
    assert modelled_filtration(0.734) == {"value_pct": 73, "label_key": "filtration.label"}


# --------------------------------------------------------------------------------------------- wording (C3, C4, 4d)
def test_trichy_penalty_is_any_aki_not_per_episode():
    p = registry()["aki_slope_penalty"]
    assert "per episode" not in p.unit and "ANY AKI" in p.unit
    assert "associated" in p.notes.lower()
    assert param("aki_penalty_max_episodes") == 2
    assert registry()["aki_penalty_extra_episode_mult"].provenance == "ASSUMPTION"


def test_old_heatstroke_figure_and_banned_wording_are_gone():
    for f in CONFIG_DIR.rglob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "48,156" not in text and "269 suspected" not in text, f.name
        assert "kidney failure" not in text.lower() or f.name == "parameters.yaml", f.name   # KFRE name only
    en = messages("en")
    assert all("kidney failure" not in v.lower() for k, v in en.items() if not k.startswith("_"))
    assert "67,637" in (CONFIG_DIR / "cohort.yaml").read_text("utf-8")


def test_audit_log_detects_tampering():
    log = AuditLog(key="k")
    for i in range(3):
        log.append("x", subject=f"P{i}")
    assert log.verify()
    log.records[1]["subject"] = "P9"
    assert not log.verify()
