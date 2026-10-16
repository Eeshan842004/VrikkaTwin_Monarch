"""Enriched high-risk heat-season cohort generator (master plan §11.2; Decisions v1 item 8, v2 A-5b).

Draws one row per synthetic patient from config/cohort.yaml. Columns starting with ``true_`` are HIDDEN: only the
ground-truth simulator may read them. Everything else is what an EHR / patient profile would hold.
All distributions are assumptions ([A]) unless config/cohort.yaml cites a source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from vrikka.config import SEED, load_yaml, param
from vrikka.physiology.equations import creatinine_from_egfr
from vrikka.physiology.pk_nsaid import ALLELE_ACTIVITY

ALLELES = ("*1", "*2", "*3")


def beta_mean_sd(rng, mean, sd, size, lo, hi):
    """Beta draws with the given mean/SD (method of moments), clipped to [lo, hi]."""
    mean = np.clip(np.asarray(mean, dtype=float), 0.02, 0.98)
    var = np.minimum(sd**2, mean * (1 - mean) * 0.95)
    k = mean * (1 - mean) / var - 1
    return np.clip(rng.beta(mean * k, (1 - mean) * k, size=size), lo, hi)


def phi_drink_mean(age, water_at_work):
    m = np.where(np.asarray(age) >= 60, param("phi_drink_old"), param("phi_drink_young"))
    return m * np.where(np.asarray(water_at_work, dtype=bool), 1.0, param("phi_drink_no_water_at_work_mult"))


def choice(rng, d: dict, size):
    keys = list(d)
    return rng.choice(keys, size=size, p=np.array([d[k] for k in keys], dtype=float) / sum(d.values()))


def generate_cohort(n: int | None = None, seed: int = SEED, id_prefix: str = "P") -> pd.DataFrame:
    """``n`` patients (default ``n_train_patients`` of cohort.yaml). The train and test pools use different seeds and
    id prefixes (P / T) so a test patient can never appear in training (Amendment 2 A2.3)."""
    c = load_yaml("cohort")
    n = n or c["n_train_patients"]
    rng = np.random.default_rng(seed)
    a = c["age"]
    age = stats.truncnorm.rvs(
        (a["min"] - a["mean"]) / a["sd"],
        (a["max"] - a["mean"]) / a["sd"],
        loc=a["mean"],
        scale=a["sd"],
        size=n,
        random_state=rng,
    ).round()
    female = rng.random(n) < c["female"]
    city = choice(rng, {k: v[2] for k, v in c["cities"].items()}, n)
    occ = choice(rng, c["occupation"], n)
    occ = np.where((age >= 70) & np.isin(occ, ["construction_farm", "delivery"]), "home", occ)  # few 70+ in heavy work
    weight = np.where(female, rng.normal(58, 10, n), rng.normal(66, 11, n)).clip(38, 115).round(1)
    height = np.where(female, rng.normal(1.53, 0.06, n), rng.normal(1.65, 0.07, n)).clip(1.38, 1.92).round(2)

    cond = c["conditions"]
    htn = rng.random(n) < cond["htn"]
    dm = rng.random(n) < cond["dm"]
    ckd_g3 = rng.random(n) < cond["ckd_g3"]
    albuminuria = ~ckd_g3 & (rng.random(n) < cond["albuminuria_g1g2"])
    hf = rng.random(n) < cond["heart_failure"]
    eg = c["egfr_baseline"]
    egfr_no = rng.normal(eg["no_ckd"][0] - 0.4 * (age - 58), eg["no_ckd"][1], n).clip(60, 125)
    egfr = np.where(ckd_g3, rng.normal(*eg["ckd_g3"], n).clip(30, 59.5), egfr_no).round(1)
    cr_base = np.array([creatinine_from_egfr(e, ag, f) for e, ag, f in zip(egfr, age, female, strict=True)]).round(3)
    uacr = np.where(
        albuminuria | (ckd_g3 & (rng.random(n) < 0.5)),
        rng.lognormal(np.log(120), 0.8, n),
        rng.lognormal(np.log(12), 0.6, n),
    ).round(1)

    mh = c["meds_given_htn"]
    on_ras = htn & (rng.random(n) < mh["acei_arb"])
    ras_kind = np.where(rng.random(n) < c["ras_split"]["arb"], "arb", "acei")
    thiazide = htn & (rng.random(n) < mh["thiazide"])
    loop = (htn & (rng.random(n) < mh["loop"])) | (hf & (rng.random(n) < 0.6))
    thiazide &= ~loop
    diuretic = np.full(n, None, dtype=object)
    for cls, mask in (("thiazide", thiazide), ("loop", loop)):
        diuretic[mask] = choice(rng, c["diuretic_generic"][cls], int(mask.sum()))
    fdc = on_ras & (ras_kind == "arb") & thiazide & (rng.random(n) < c["fixed_dose_combo_share"])
    md = c["meds_given_dm"]
    beta_blocker = (htn & (rng.random(n) < mh["beta_blocker"])) | (hf & (rng.random(n) < 0.7))

    g = c["cyp2c9_allele_freq"]
    p_all = [1 - g["*2"] - g["*3"], g["*2"], g["*3"]]
    a1, a2 = rng.choice(ALLELES, n, p=p_all), rng.choice(ALLELES, n, p=p_all)
    genotype = np.array([f"{min(x, y)}/{max(x, y)}" for x, y in zip(a1, a2, strict=True)])
    act = np.array([ALLELE_ACTIVITY[x] + ALLELE_ACTIVITY[y] for x, y in zip(a1, a2, strict=True)])

    routine = c["occupation_routine"]
    outdoor_workers = np.isin(occ, ["vendor", "delivery", "construction_farm"])
    water_at_work = ~outdoor_workers | (rng.random(n) < c["water_access_at_work_outdoor"])
    works_sunday = rng.random(n) < np.array([routine[o]["works_sunday"] for o in occ])

    df = pd.DataFrame(
        {
            "patient_id": [f"{id_prefix}{i:05d}" for i in range(n)],
            "age": age.astype(int),
            "female": female,
            "weight_kg": weight,
            "height_m": height,
            "city": city,
            "language": [load_yaml("cities")[x]["default_language"] for x in city],
            "occupation": occ,
            "outdoor_start": [routine[o]["outdoor_start"] for o in occ],
            "outdoor_hours": [routine[o]["outdoor_hours"] for o in occ],
            "works_sunday": works_sunday,
            "water_access_at_work": water_at_work,
            "roof": choice(rng, c["housing_roof"], n),
            "cooling": choice(rng, c["cooling_at_home"], n),
            "htn": htn,
            "dm": dm,
            "ckd_g3": ckd_g3,
            "albuminuria": albuminuria,
            "heart_failure": hf,
            "egfr_baseline": egfr,
            "cr_baseline": cr_base,
            "uacr_mg_g": uacr,
            "on_ras": on_ras,
            "ras_kind": np.where(on_ras, ras_kind, None),
            "diuretic": diuretic,
            "fixed_dose_combo": fdc,
            "on_mra": htn & (rng.random(n) < mh["mra"]),
            "on_ccb": htn & (rng.random(n) < mh["ccb"]),
            "beta_blocker": beta_blocker,
            "on_metformin": dm & (rng.random(n) < md["metformin"]),
            "on_sglt2i": dm & (rng.random(n) < md["sglt2i"]),
            "on_sulfonylurea": dm & (rng.random(n) < md["sulfonylurea"]),
            "chronic_pain": rng.random(n) < c["chronic_pain"] * np.where(age >= 60, 1.4, 0.7),
            "gout": rng.random(n) < c["gout"],
            "cyp2c9_genotype": genotype,
            "cyp2c9_as": act,
            "tier": choice(rng, c["wearable_tier_share"], n),
            "hr_base": (rng.normal(74, 8, n) - 10 * beta_blocker).round(1),
            "sbp_base": np.where(htn, rng.normal(136, 13, n), rng.normal(121, 10, n)).round(0),
            "dbp_base": np.where(htn, rng.normal(84, 8, n), rng.normal(78, 7, n)).round(0),
            "lives_alone": rng.random(n) < np.where(age >= 65, 0.18, 0.06),
        }
    )
    # Baseline lab panel (for the R2 plausibility overlay only); [A]
    ckd = egfr < 60
    df["hb_g_dl"] = (np.where(female, rng.normal(12.2, 1.3, n), rng.normal(13.9, 1.4, n)) - 1.3 * ckd).round(1)
    df["urea_mg_dl"] = (rng.lognormal(np.log(26), 0.25, n) * (90 / np.maximum(egfr, 15)) ** 0.8).round(0)
    df["sodium_mmol_l"] = rng.normal(139, 2.8, n).round(0)
    df["potassium_mmol_l"] = (rng.normal(4.3, 0.4, n) + 0.3 * ckd + 0.15 * on_ras + 0.3 * df["on_mra"]).round(1)

    # ---- hidden truth (simulator only) ----
    df["true_phi_drink"] = beta_mean_sd(
        rng,
        phi_drink_mean(age, water_at_work),
        param("phi_drink_sd"),
        n,
        param("phi_drink_min"),
        param("phi_drink_max"),
    )
    df["true_theta_sweat"] = rng.lognormal(0.0, 0.25, n)
    df["true_tau_recover_h"] = rng.uniform(8, 18, n)
    df["true_ecf_frac_sweat"] = rng.uniform(0.35, 0.65, n)
    df["true_k_map"] = rng.uniform(6, 12, n)  # mmHg MAP fall per L of ECF deficit
    df["true_lla"] = (75 + 0.25 * (age - 50) + 8 * htn + 8 * ckd + rng.normal(0, 4, n)).round(1)
    df["true_diuretic_loss_mult"] = rng.uniform(0.6, 1.4, n)
    df["true_k_hr"] = rng.uniform(5, 11, n) * np.where(beta_blocker, param("k_hr_beta_blocker_mult"), 1.0)
    df["true_k_bp"] = rng.uniform(3, 8, n)
    # Exertional GFR fall (Decisions v4 2b / v5 C2, pre-registered in Amendment 2 A2.4): the world's own values,
    # centred on 0.25 / 1 h but independent of the twin's registry so a sensitivity sweep on the twin does not move
    # the truth. Not fitted to L4 or L5.
    df["true_k_ex"] = np.clip(0.25 * rng.lognormal(0.0, 0.30, n), 0.10, 0.40)
    df["true_tau_ex_h"] = rng.uniform(0.5, 2.0, n)
    df["true_adherence"] = rng.uniform(*c["adherence"], n)
    df["true_wear_time"] = rng.uniform(*c["wear_time"], n)
    df["true_sigma_weight_mult"] = rng.uniform(0.75, 1.25, n)
    return df


def public_columns(df: pd.DataFrame) -> list[str]:
    """Columns the twin / fast clock may use (never the hidden truth)."""
    return [col for col in df.columns if not col.startswith("true_")]
