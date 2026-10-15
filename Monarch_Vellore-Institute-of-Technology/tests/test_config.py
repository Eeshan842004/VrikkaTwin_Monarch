"""The parameter registry and config files are complete and well-formed (master plan §8, §11.2, §12.5, App. B)."""
import pytest

from vrikka.config import load_yaml, param, param_range, registry

# Every row of the §8 registry table, as registry keys.
SECTION_8_KEYS = [
    "ecv_frac", "tbw_frac_female", "tbw_frac_male", "tbw_frac_young_bonus", "d50", "ecf_frac_sweat",
    "ecf_frac_gi", "ecf_frac_drug", "half_life_nsaid_h", "half_life_ras_h", "half_life_hctz_h",
    "half_life_chlorthalidone_h", "half_life_loop_h", "half_life_sglt2_h", "hill_n", "a_tot_young", "a_tot_old",
    "aff_share", "i_ras", "nsaid_e50", "phi_drink_young", "phi_drink_old", "phi_drink_no_water_at_work_mult",
    "tau_recover_h", "forecast_sd_day1_c", "forecast_sd_day2_c", "forecast_sd_day3_c",
    "paracetamol_ceiling_g_day", "paracetamol_ceiling_high_risk_g_day", "diuretic_loss_thiazide_l_day",
    "diuretic_loss_loop_l_day", "sglt2_loss_l_day", "fever_loss_l_day_per_c", "vomit_loss_l", "diarrhoea_loss_l",
    "k_hr", "k_hr_beta_blocker_mult", "k_bp", "sigma_weight_kg", "sigma_hr_bpm", "sigma_hr_beta_blocker_bpm",
    "cr_lab_cv", "tr_offset_sun_c", "met_home", "met_office", "met_vendor", "met_delivery", "met_construction_farm",
    "clo_light_cotton", "clo_sari_salwar", "cyp2c9_mult_as_2_0", "cyp2c9_mult_as_1_5", "cyp2c9_mult_as_1_0",
    "cyp2c9_mult_as_0_5", "cyp2c9_mult_as_0_0", "aki_step_stage1", "aki_step_stage2", "aki_step_stage3",
    "aki_slope_penalty", "slope_prior_htn_no_dm", "slope_prior_dm_htn", "slope_prior_dkd_albuminuria",
    "slope_prior_sd", "sglt2i_slope_effect", "sglt2i_hazard_ratio", "finerenone_hazard_ratio",
    "sbp_control_slope_effect_per_10mmhg", "kfre_s0_2y_non_na", "kfre_s0_5y_non_na",
]


def test_every_section_8_parameter_is_registered():
    missing = [k for k in SECTION_8_KEYS if k not in registry()]
    assert not missing, f"missing from parameters.yaml: {missing}"


def test_every_parameter_has_provenance_source_and_range():
    for name, p in registry().items():
        assert p.source, name
        lo, hi = p.range
        assert lo <= p.value <= hi or name.startswith("missing_channel"), f"{name}: value outside its range"


def test_assumptions_have_a_real_sensitivity_range():
    """Fixed-width ranges are allowed only for normalisation/unit constants, never for tunable physiology."""
    fixed_ok = {"ukf_kappa", "missing_channel_r", "cyp2c9_mult_as_2_0", "creatinine_umol_detect_threshold",
                "sweat_sensitivity_low", "sweat_sensitivity_high", "creatinine_sample_hour"}
    fixed_ok |= {k for k in registry() if k.startswith("nsaid_unit_")}
    for name, p in registry().items():
        if p.provenance == "ASSUMPTION" and name not in fixed_ok:
            assert p.range[0] < p.range[1], f"{name} is an ASSUMPTION without a sensitivity range"


def test_param_lookup_and_unknown_name():
    assert param("d50") == pytest.approx(0.065)
    assert param_range("d50") == (0.04, 0.10)
    with pytest.raises(KeyError):
        param("made_up_constant")


def test_cohort_yaml_matches_plan():
    c = load_yaml("cohort")
    assert c["n_patients"] == 3000
    assert abs(sum(v[2] for v in c["cities"].values()) - 1.0) < 1e-9
    assert abs(sum(c["occupation"].values()) - 1.0) < 1e-9
    assert abs(sum(c["nsaid_mix"].values()) - 1.0) < 1e-9
    assert abs(sum(c["wearable_tier_share"].values()) - 1.0) < 1e-9
    assert c["cyp2c9_allele_freq"] == {"*2": 0.03, "*3": 0.11}


def test_cities_and_alert_policy():
    cities = load_yaml("cities")
    assert len(cities) == 7 and "Palasa" in cities
    pol = load_yaml("alert_policy")
    assert pol["alert_budget_per_100_patient_days"] == 3
    assert all("icon" in v and "word_key" in v for v in pol["levels"].values()), "never colour alone"


def test_drug_lexicon_has_key_brands_and_combinations():
    d = load_yaml("drugs_india")["brands"]
    assert set(d["combiflam"]["generics"]) == {"ibuprofen", "paracetamol"}
    assert d["combiflam"]["paracetamol_mg"] == 325
    assert d["telma_h"]["class"] == ["arb", "thiazide"]
    assert d["voveran"]["class"] == "nsaid_other"   # diclofenac: no CYP2C9 adjustment
    assert d["dolo"]["class"] == "analgesic_safe"


def test_symptom_lexicon_covers_supported_languages():
    """Supported languages are EN, HI, KN, TE (Decisions v1 item 16); extra seed entries are harmless."""
    s = load_yaml("symptoms_lexicon")
    for symptom in ("fever", "vomiting", "diarrhoea", "dizziness", "less_urine"):
        assert {"en", "hi", "kn", "te"} <= set(s[symptom]), symptom


def test_cities_use_supported_languages():
    assert {c["default_language"] for c in load_yaml("cities").values()} <= {"en", "hi", "kn", "te"}


def test_cpic_classification_of_nsaids():
    g = load_yaml("drugs_india")["generics"]
    for drug in ("ibuprofen", "celecoxib", "flurbiprofen", "lornoxicam", "meloxicam", "piroxicam", "tenoxicam"):
        assert g[drug] == "nsaid_cyp2c9", drug
    for drug in ("diclofenac", "aceclofenac", "naproxen", "indomethacin", "nimesulide"):
        assert g[drug] == "nsaid_other", drug


def test_sglt2_has_no_aki_raising_volume_effect_by_default():
    assert param("sglt2_loss_l_day") == 0.0
