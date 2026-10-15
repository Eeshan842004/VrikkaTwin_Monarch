"""Wearable / scale / BP-cuff observations from the ground truth (master plan §7.4), plus export shapes.

Tiers: T0 = no wearable (weekly ASHA weight + BP), T1 = band (resting HR, steps, sleep) + scale, T2 = T1 + home BP
cuff + skin temperature. Missingness: band wear time per patient, scale use 80 %, weekend gaps.
Exports: HealthKit-like JSON, Google-Fit-like dataPoint JSON and FHIR R4 Observation (all three are accepted by the
ingestion path). Device signing is a single Ed25519 unit test in Part 6 (Decisions v1 item 16).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.config import load_yaml, param

LOINC = {
    "weight": ("29463-7", "kg"),
    "resting_hr": ("8867-4", "/min"),
    "sbp": ("8480-6", "mm[Hg]"),
    "steps": ("55423-8", "{steps}"),
}
HEALTHKIT = {
    "weight": "HKQuantityTypeIdentifierBodyMass",
    "resting_hr": "HKQuantityTypeIdentifierRestingHeartRate",
    "steps": "HKQuantityTypeIdentifierStepCount",
}
GOOGLEFIT = {
    "weight": "com.google.weight",
    "resting_hr": "com.google.heart_rate.bpm",
    "steps": "com.google.step_count.delta",
}


def simulate_observations(
    people: pd.DataFrame, truth: dict, ev: dict, dates: pd.DatetimeIndex, rng: np.random.Generator
) -> pd.DataFrame:
    """One row per patient-day at 08:00. NaN = not measured that day."""
    c = load_yaml("cohort")
    D, N = truth["cr_0800"].shape
    tier = people["tier"].to_numpy()
    dow = np.asarray(dates.dayofweek)[:, None]
    weekend = dow >= 5
    band = (
        (tier != "T0")[None, :]
        & (rng.random((D, N)) < people["true_wear_time"].to_numpy()[None, :])
        & ~(weekend & (rng.random((D, N)) < 0.3))
    )
    scale = np.where((tier == "T0")[None, :], dow == c["asha_visit_weekday"], rng.random((D, N)) < c["scale_use"])
    cuff = np.where(
        (tier == "T2")[None, :], rng.random((D, N)) < 0.8, (tier == "T0")[None, :] & (dow == c["asha_visit_weekday"])
    )

    bb = people["beta_blocker"].to_numpy()[None, :]
    sig_hr = param("sigma_hr_bpm") * np.where(bb, param("sigma_hr_beta_blocker_mult"), 1.0)
    sig_w = param("sigma_weight_kg") * people["true_sigma_weight_mult"].to_numpy()[None, :]
    dry = people["weight_kg"].to_numpy()[None, :] + np.cumsum(rng.normal(0, 0.05, (D, N)), axis=0)
    weight = dry - truth["v_tot_0800"] + rng.normal(0, 1, (D, N)) * sig_w
    hr = (
        people["hr_base"].to_numpy()[None, :]
        + people["true_k_hr"].to_numpy()[None, :] * truth["v_ecf_0800"]
        + param("hr_fever_bpm_per_c") * ev["fever_excess_c"]
        + rng.normal(0, 1, (D, N)) * sig_hr
    )
    sbp = (
        people["sbp_base"].to_numpy()[None, :]
        - people["true_k_bp"].to_numpy()[None, :] * truth["v_ecf_0800"]
        + rng.normal(0, param("sigma_sbp_mmhg"), (D, N))
    )
    outdoor = people["outdoor_hours"].to_numpy()[None, :]
    steps = np.maximum(
        rng.normal(3500 + 1100 * outdoor, 1500, (D, N)) * np.where(ev["fever_excess_c"] > 0, 0.5, 1.0), 0
    )
    sleep = np.clip(rng.normal(6.8, 0.8, (D, N)) - 0.6 * (ev["fever_excess_c"] > 0), 3, 10)
    skin = ev["fever_excess_c"] * 0.6 + rng.normal(0, 0.2, (D, N))

    frame = {
        "patient_id": np.repeat(people["patient_id"].to_numpy()[None, :], D, 0).ravel(),
        "day": np.repeat(np.arange(D)[:, None], N, 1).ravel(),
        "date": np.repeat(np.asarray(dates)[:, None], N, 1).ravel(),
        "weight_morning": np.where(scale, weight.round(1), np.nan).ravel(),
        "resting_hr": np.where(band, hr.round(0), np.nan).ravel(),
        "sbp_home": np.where(cuff, sbp.round(0), np.nan).ravel(),
        "steps": np.where(band, steps.round(-1), np.nan).ravel(),
        "sleep_hours": np.where(band, sleep.round(1), np.nan).ravel(),
        "skin_temp_delta": np.where(band & (tier == "T2")[None, :], skin.round(1), np.nan).ravel(),
        "wear_time_pct": np.where(band, 100.0, 0.0).ravel(),
        "rep_fever_excess_c": ev["rep_fever_excess_c"].round(1).ravel(),
        "rep_vomit_episodes": ev["rep_vomit_episodes"].ravel(),
        "rep_diarrhoea_episodes": ev["rep_diarrhoea_episodes"].ravel(),
        "rep_poor_intake": ev["rep_poor_intake"].ravel(),
        "rep_nsaid_on": ev["rep_nsaid_on"].ravel(),
        "rep_nsaid_generic": np.where(ev["rep_nsaid_on"], ev["nsaid_generic"], "").ravel(),
        "rep_ors_l_day": ev["rep_ors_l_day"].round(2).ravel(),
    }
    return pd.DataFrame(frame)


def to_healthkit(pid: str, date: str, kind: str, value: float) -> dict:
    unit = {"weight": "kg", "resting_hr": "count/min", "steps": "count"}[kind]
    return {
        "type": HEALTHKIT[kind],
        "sourceName": "VrikkaTwin-sim",
        "startDate": date,
        "endDate": date,
        "value": value,
        "unit": unit,
        "metadata": {"patient": pid},
    }


def to_googlefit(pid: str, date_ns: int, kind: str, value: float) -> dict:
    return {
        "dataTypeName": GOOGLEFIT[kind],
        "startTimeNanos": date_ns,
        "endTimeNanos": date_ns,
        "value": [{"fpVal": value}],
        "originDataSourceId": f"vrikka-sim:{pid}",
    }


def to_fhir_observation(pid: str, date: str, kind: str, value: float) -> dict:
    code, unit = LOINC[kind]
    return {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
        "subject": {"reference": f"Patient/{pid}"},
        "effectiveDateTime": date,
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }
