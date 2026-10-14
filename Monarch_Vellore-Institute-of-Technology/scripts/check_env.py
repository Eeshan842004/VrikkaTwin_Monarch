"""Environment smoke test (master plan §17, §9.2).

Imports every core library, records its version and runs six micro-checks that catch the API traps
the plan warns about. Writes reports/env_check.json and exits non-zero if any check fails.
"""
from __future__ import annotations

import importlib
import json
import math
import platform
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = [
    "numpy", "scipy", "pandas", "pyarrow", "yaml", "pydantic", "pythermalcomfort", "filterpy", "lightgbm",
    "sklearn", "shap", "lifelines", "kfre", "duckdb", "fastapi", "uvicorn", "sqlmodel", "httpx", "streamlit",
    "plotly", "matplotlib", "cryptography", "jwt", "bcrypt", "faster_whisper", "gtts", "rapidfuzz", "joblib",
]


def check_phs():
    """§9.2: met is in met units; 62 kg, 1.6 m, clo 0.5, tr = tdb + 8, 40 °C / 40 % / met 2.5 → ~0.61 L/h."""
    from pythermalcomfort.models import phs

    r = phs(tdb=40, tr=48, v=0.5, rh=40, met=2.5, clo=0.5, posture="standing", duration=60,
            weight=62, height=1.6, round_output=False)
    litres = float(r.sweat_loss_g) / 1000.0
    return 0.45 <= litres <= 0.75, {"sweat_l_per_h": round(litres, 3), "plan_value": 0.61}


def check_filterpy():
    """filterpy 1.4.5 is from 2018: confirm UKF predict/update still works on numpy 2.x."""
    import numpy as np
    from filterpy.kalman import MerweScaledSigmaPoints, UnscentedKalmanFilter

    pts = MerweScaledSigmaPoints(n=2, alpha=0.3, beta=2.0, kappa=0.0)
    ukf = UnscentedKalmanFilter(dim_x=2, dim_z=1, dt=1.0, hx=lambda x: x[:1],
                                fx=lambda x, dt: x + [x[1], 0], points=pts)
    ukf.x, ukf.P, ukf.R, ukf.Q = np.array([0.0, 1.0]), np.eye(2), np.eye(1) * 0.1, np.eye(2) * 0.01
    for z in (1.1, 1.9, 3.05):
        ukf.predict()
        ukf.update(np.array([z]))
    ok = bool(np.all(np.isfinite(ukf.x))) and abs(ukf.x[0] - 3.0) < 0.3
    return ok, {"x": [round(float(v), 3) for v in ukf.x], "numpy": np.__version__}


def check_lightgbm():
    """§12.4: native lgb.train works (sklearn eval_set is deprecated in 4.7)."""
    import lightgbm as lgb
    import numpy as np

    rng = np.random.default_rng(42)
    X = rng.normal(size=(400, 3))
    y = (X[:, 0] + 0.3 * rng.normal(size=400) > 0).astype(int)
    b = lgb.train({"objective": "binary", "verbose": -1, "seed": 42}, lgb.Dataset(X, y), num_boost_round=20)
    contrib = b.predict(X[:2], pred_contrib=True)
    return contrib.shape == (2, 4), {"pred_contrib_shape": list(contrib.shape)}


def check_kfre():
    """§9.3 golden: M 65 y, eGFR 35, UACR 300, non-North-American → 2 y 0.0305, 5 y 0.1132."""
    import kfre

    two = float(kfre.kfre_person(age=65, is_male=True, eGFR=35, uACR=300, is_north_american=False, years=2))
    five = float(kfre.kfre_person(age=65, is_male=True, eGFR=35, uACR=300, is_north_american=False, years=5))
    ok = math.isclose(two, 0.0305, abs_tol=5e-4) and math.isclose(five, 0.1132, abs_tol=5e-4)
    return ok, {"kfre_2y": round(two, 4), "kfre_5y": round(five, 4)}


def check_streamlit_audio():
    """§23.5: st.audio_input powers the voice check-in."""
    import streamlit as st

    return hasattr(st, "audio_input"), {"has_audio_input": hasattr(st, "audio_input")}


def check_faster_whisper():
    """§23.5: import only; the model itself is downloaded in Part 7."""
    from faster_whisper import WhisperModel  # noqa: F401

    return True, {"import": "ok"}


def main() -> int:
    out = {"python": sys.version.split()[0], "platform": platform.platform(), "versions": {}, "checks": {}}
    for name in LIBS:
        try:
            m = importlib.import_module(name)
            out["versions"][name] = getattr(m, "__version__", "unknown")
        except Exception as exc:  # pragma: no cover - reported, not raised
            out["versions"][name] = f"IMPORT FAILED: {exc}"
    failed = [n for n, v in out["versions"].items() if str(v).startswith("IMPORT FAILED")]

    for name, fn in [("phs_met_units", check_phs), ("filterpy_ukf_numpy2", check_filterpy),
                     ("lightgbm_native_train", check_lightgbm), ("kfre_golden", check_kfre),
                     ("streamlit_audio_input", check_streamlit_audio), ("faster_whisper_import", check_faster_whisper)]:
        try:
            ok, detail = fn()
        except Exception:
            ok, detail = False, {"error": traceback.format_exc(limit=2)}
        out["checks"][name] = {"pass": bool(ok), **detail}
        if not ok:
            failed.append(name)

    out["all_pass"] = not failed
    out["failed"] = failed
    dest = ROOT / "reports" / "env_check.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    for name, c in out["checks"].items():
        print(f"{'PASS' if c['pass'] else 'FAIL'}  {name}  {({k: v for k, v in c.items() if k != 'pass'})}")
    print(f"\n{len(LIBS) - len([f for f in failed if f in LIBS])}/{len(LIBS)} libraries import; "
          f"{'ALL CHECKS PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
