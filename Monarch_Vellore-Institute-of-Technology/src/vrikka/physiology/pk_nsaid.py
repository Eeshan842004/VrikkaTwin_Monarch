"""Tablets -> NSAID exposure units with the CYP2C9 multiplier; paracetamol tally (master plan §7.2, §7.3).

Normalised units: ibuprofen 1,200 mg/day = 1.0; diclofenac 100; aceclofenac 200; nimesulide 200 (registry
``nsaid_unit_*_mg_day``). The CYP2C9 multiplier applies only to drugs CPIC 2020 covers with a CYP2C9
recommendation (class ``nsaid_cyp2c9``); diclofenac, aceclofenac and other "no recommendation" drugs, and
nimesulide (not addressed by CPIC), get no genotype effect (Decisions v1 item 13).
"""
from __future__ import annotations

from vrikka.config import load_yaml, param

ALLELE_ACTIVITY = {"*1": 1.0, "*2": 0.5, "*3": 0.0}


def activity_score(genotype: str) -> float:
    """CYP2C9 activity score from a diplotype such as '*1/*3' (-> 1.0)."""
    a, b = genotype.split("/")
    return ALLELE_ACTIVITY[a.strip()] + ALLELE_ACTIVITY[b.strip()]


def cyp2c9_multiplier(score: float) -> float:
    """NSAID exposure multiplier for a CYP2C9 activity score (registry ``cyp2c9_mult_as_*``)."""
    return param(f"cyp2c9_mult_as_{score:.1f}".replace(".", "_"))


def nsaid_units_per_day(generic: str, mg_per_day: float, score: float = 2.0) -> float:
    """Genotype-adjusted normalised NSAID units for one drug. Non-NSAIDs (e.g. paracetamol) give 0."""
    cls = load_yaml("drugs_india")["generics"].get(generic)
    if cls not in ("nsaid_cyp2c9", "nsaid_other"):
        return 0.0
    units = mg_per_day / param(f"nsaid_unit_{generic}_mg_day")
    return units * (cyp2c9_multiplier(score) if cls == "nsaid_cyp2c9" else 1.0)


def brand_daily_mg(brand: str, tablets_per_day: float) -> dict[str, float]:
    """mg/day of each generic in a brand (e.g. Combiflam x3 -> ibuprofen 1200, paracetamol 975)."""
    b = load_yaml("drugs_india")["brands"][brand.lower()]
    return {g: b[f"{g}_mg"] * tablets_per_day for g in b["generics"] if f"{g}_mg" in b}


def nsaid_units_from_tablets(brand: str, tablets_per_day: float, score: float = 2.0) -> float:
    return sum(nsaid_units_per_day(g, mg, score) for g, mg in brand_daily_mg(brand, tablets_per_day).items())


def paracetamol_mg_per_day(tablets: dict[str, float]) -> float:
    """Total paracetamol across brands, counting the 325 mg in each Combiflam (guardrail input, §14.2)."""
    return sum(brand_daily_mg(b, n).get("paracetamol", 0.0) for b, n in tablets.items())
