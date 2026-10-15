"""R2: plausibility overlay of our synthetic baseline labs vs UCI CKD (Decisions v1 item 14, v2 B3).

Our CKD subgroup (eGFR < 60) vs UCI CKD 'ckd' patients; our non-CKD patients vs UCI 'notckd'. Overlay plots and
summary statistics only - no pass/fail KS claim. UCI origin: the UCI page names no hospital, city or country
(only "collected from the hospital nearly 2 months", donated 2015, CC BY 4.0); we do not state a site.
BD-KDD (Zenodo 18971931) was assessed for this overlay and NOT used: its values look synthetic (docs/DATA_SEARCH.md).
Writes reports/r2_overlay.json and reports/figures/r2_overlay.png.
"""

from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from vrikka.config import DATA_DIR, REPORTS_DIR  # noqa: E402
from vrikka.simulator.cohort import generate_cohort  # noqa: E402

PAIRS = {
    "creatinine (mg/dL)": ("cr_baseline", "sc"),
    "blood urea (mg/dL)": ("urea_mg_dl", "bu"),
    "haemoglobin (g/dL)": ("hb_g_dl", "hemo"),
    "sodium (mmol/L)": ("sodium_mmol_l", "sod"),
    "potassium (mmol/L)": ("potassium_mmol_l", "pot"),
    "age (years)": ("age", "age"),
}


def q(x) -> dict:
    x = pd.to_numeric(pd.Series(x), errors="coerce").dropna()
    return {
        "n": int(x.size),
        "median": round(float(x.median()), 2),
        "p25": round(float(x.quantile(0.25)), 2),
        "p75": round(float(x.quantile(0.75)), 2),
    }


def main() -> int:
    ours = generate_cohort()
    uci = pd.read_csv(DATA_DIR / "raw" / "uci_ckd" / "uci_ckd.csv")
    uci["class"] = uci["class"].astype(str).str.strip()  # one label is 'ckd\t' in the source file
    uci = uci[uci["pot"].isna() | (uci["pot"] < 20)]  # two potassium entries (39, 47) are data errors
    groups = {
        "CKD": (ours[ours["egfr_baseline"] < 60], uci[uci["class"] == "ckd"]),
        "non-CKD": (ours[ours["egfr_baseline"] >= 60], uci[uci["class"] == "notckd"]),
    }
    out = {
        "uci_origin": "not stated on the UCI page (no hospital/city/country); CC BY 4.0; donated 2015",
        "claim": "plausibility overlay only, no pass/fail",
        "groups": {},
    }
    fig, axes = plt.subplots(2, len(PAIRS), figsize=(3.2 * len(PAIRS), 6))
    for r, (g, (o, u)) in enumerate(groups.items()):
        out["groups"][g] = {}
        for c, (label, (oc, uc)) in enumerate(PAIRS.items()):
            out["groups"][g][label] = {"synthetic": q(o[oc]), "uci": q(u[uc])}
            ax = axes[r, c]
            uv = pd.to_numeric(u[uc], errors="coerce").dropna()
            bins = np.histogram_bin_edges(np.r_[o[oc].to_numpy(float), uv.to_numpy(float)], bins=30)
            ax.hist(o[oc], bins=bins, density=True, alpha=0.55, label=f"synthetic (n={len(o)})", color="#2a7f62")
            ax.hist(uv, bins=bins, density=True, alpha=0.55, label=f"UCI (n={uv.size})", color="#c9822b")
            ax.set_title(f"{g}: {label}", fontsize=9)
            ax.tick_params(labelsize=7)
            if c == 0:
                ax.legend(fontsize=7)
    fig.suptitle("R2 plausibility overlay: synthetic cohort vs UCI CKD (no pass/fail claim)", fontsize=11)
    fig.tight_layout()
    (REPORTS_DIR / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(REPORTS_DIR / "figures" / "r2_overlay.png", dpi=110)
    (REPORTS_DIR / "r2_overlay.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    for g, rows in out["groups"].items():
        print(g)
        for label, v in rows.items():
            syn, uci_q = v["synthetic"], v["uci"]
            print(
                f"  {label:22s} synthetic median {syn['median']:8.2f} [{syn['p25']}-{syn['p75']}]"
                f"   UCI median {uci_q['median']:8.2f} [{uci_q['p25']}-{uci_q['p75']}] (n={uci_q['n']})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
