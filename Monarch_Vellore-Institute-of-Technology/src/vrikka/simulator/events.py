"""Daily event processes for the synthetic cohort (master plan §11.1-§11.2). Arrays are shaped (D days, N patients).

True events feed the ground-truth simulator; the *reported* versions (symptoms, tablets) are what the twin sees.
Rates come from config/cohort.yaml ([A] unless cited there).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.config import load_yaml
from vrikka.physiology.pk_nsaid import nsaid_units_per_day

NSAID_GENERIC = {
    "diclofenac": "diclofenac",
    "ibuprofen_combiflam": "ibuprofen",
    "aceclofenac": "aceclofenac",
    "nimesulide": "nimesulide",
    "other": "ibuprofen",
}


def _episodes(rng, rate_per_day: np.ndarray, days: int, dur: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Poisson episode starts with random durations -> (active (D,N) bool, start (D,N) bool)."""
    n = rate_per_day.shape[0]
    start = rng.random((days, n)) < rate_per_day[None, :]
    active = np.zeros((days, n), dtype=bool)
    for d, i in zip(*np.nonzero(start), strict=True):
        active[d : d + rng.integers(dur[0], dur[1] + 1), i] = True
    return active, start


def simulate_events(
    people: pd.DataFrame, days: int, rng: np.random.Generator, tmax_city: np.ndarray | None = None
) -> dict[str, np.ndarray]:
    """All daily event arrays. ``tmax_city`` (D, N) lets summer gastroenteritis rise slightly on hotter days."""
    c = load_yaml("cohort")
    n = len(people)
    per_day = {k: v / 100 / 30 for k, v in c["illness_rates_per_100_patient_months"].items()}
    ill = c["illness_days"]

    fever, fever_start = _episodes(rng, np.full(n, per_day["fever"]), days, ill["fever"])
    gi_rate = np.full(n, per_day["gastroenteritis_summer"])
    gi, gi_start = _episodes(rng, gi_rate, days, ill["gastroenteritis_summer"])
    sepsis, _ = _episodes(rng, np.full(n, per_day["sepsis_like_background"]), days, ill["sepsis_like_background"])

    fever_excess = np.where(fever, rng.uniform(0.8, 2.2, (days, n)), 0.0)
    vomit = np.where(gi, rng.poisson(1.5, (days, n)), 0)
    diarrhoea = np.where(gi, rng.poisson(3.0, (days, n)), 0)
    poor_intake = fever | (gi & (rng.random((days, n)) < 0.7))

    # Painkiller episodes: background rate by pain/gout, plus self-medication when a fever starts.
    r = c["nsaid_episode_rate_per_month"]
    base = (
        r["base"] + r["chronic_pain"] * people["chronic_pain"].to_numpy() + r["gout"] * people["gout"].to_numpy()
    ) / 30
    nsaid_on, _ = _episodes(rng, base, days, tuple(c["nsaid_episode_days"]))
    trig = fever_start & (rng.random((days, n)) < c["nsaid_given_pain_or_fever"])
    for d, i in zip(*np.nonzero(trig), strict=True):
        nsaid_on[d : d + rng.integers(2, 5), i] = True
    mix = c["nsaid_mix"]
    drug_of_patient = rng.choice(list(mix), size=n, p=np.array(list(mix.values())) / sum(mix.values()))
    generic = np.array([NSAID_GENERIC[x] for x in drug_of_patient])
    mg = np.array([c["nsaid_daily_mg"][g] for g in generic])
    units_true = np.array(
        [nsaid_units_per_day(g, m, s) for g, m, s in zip(generic, mg, people["cyp2c9_as"].to_numpy(), strict=True)]
    )
    nsaid_units = np.where(nsaid_on, units_true[None, :], 0.0)

    ors = np.where(
        (fever | gi) & (rng.random((days, n)) < c["ors_use_when_ill"]), rng.uniform(0.5, 1.0, (days, n)), 0.0
    )
    adherent = rng.random((days, n)) < people["true_adherence"].to_numpy()[None, :]

    # Hidden causes the twin cannot see (§11.1): exertional muscle breakdown in heavy outdoor workers on workdays,
    # and co-trimoxazole courses (raise creatinine by blocking secretion; can also be real AKI).
    heavy = people["occupation"].isin(["construction_farm", "delivery"]).to_numpy()
    rhabdo, _ = _episodes(rng, np.where(heavy, 0.5 / 100 / 30 * 4, 0.0), days, (2, 3))
    cotrim, _ = _episodes(rng, np.full(n, 1.0 / 100 / 30), days, (5, 7))
    extra_outdoor = np.where(
        people["outdoor_hours"].to_numpy()[None, :] >= 8,
        rng.integers(-1, 2, (days, n)),
        rng.integers(0, 2, (days, n)) * (rng.random((days, n)) < 0.15),
    )

    report_sym = rng.random((days, n)) < c["symptom_report_prob"]
    report_tab = rng.random((days, n)) < c["tablet_report_prob"]
    return {
        "fever_excess_c": fever_excess,
        "vomit_episodes": vomit,
        "diarrhoea_episodes": diarrhoea,
        "poor_intake": poor_intake,
        "nsaid_units": nsaid_units,
        "nsaid_generic": np.broadcast_to(generic, (days, n)),
        "nsaid_on": nsaid_on,
        "ors_l_day": ors,
        "adherent": adherent,
        "sepsis_like": sepsis,
        "rhabdo": rhabdo,
        "cotrimoxazole": cotrim,
        "extra_outdoor_h": extra_outdoor,
        # what the twin is told (patient / ASHA reports)
        "rep_fever_excess_c": np.where(report_sym, fever_excess, 0.0),
        "rep_vomit_episodes": np.where(report_sym, vomit, 0),
        "rep_diarrhoea_episodes": np.where(report_sym, diarrhoea, 0),
        "rep_poor_intake": poor_intake & report_sym,
        "rep_nsaid_on": nsaid_on & report_tab,
        "rep_ors_l_day": np.where(report_sym, ors, 0.0),
    }
