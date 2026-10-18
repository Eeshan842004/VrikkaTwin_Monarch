"""Cross-platform task runner (mirrors the Makefile; Windows has no make).

Usage:  python tasks.py <target> [<target> ...]
Run from the team folder. Uses the project venv (.venv) if it exists.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def script(name: str, *extra: str) -> None:
    path = ROOT / "scripts" / name
    if not path.exists():
        sys.exit(f"{name} is not built yet (see BUILD plan). Nothing to run.")
    run(PY, str(path), *extra)


def setup() -> None:
    run("uv", "venv", ".venv", "--python", "3.12")
    run("uv", "pip", "install", "--python", ".venv", "-r", "requirements.lock")
    run("uv", "pip", "install", "--python", ".venv", "-e", ".")


def demo() -> None:
    """Start the API (:8000) and the Streamlit app (:8501) as two processes (never chained, §26)."""
    api = subprocess.Popen([PY, "-m", "uvicorn", "vrikka.api.main:app", "--port", "8000"], cwd=ROOT)
    time.sleep(2)
    app = subprocess.Popen([PY, "-m", "streamlit", "run", "app/Home.py", "--server.port", "8501"], cwd=ROOT)
    try:
        app.wait()
    finally:
        api.terminate()


TARGETS = {
    "setup": setup,
    "check-env": lambda: script("check_env.py"),
    "data": lambda: (script("fetch_weather.py"), script("download_public_data.py")),
    "validate-db": lambda: script("build_validation_duckdb.py"),
    "cohort": lambda: (script("generate_cohort.py"), script("make_demo_patients.py")),
    "features": lambda: script("build_features.py"),
    "train": lambda: script("train_fastclock.py"),
    "eval": lambda: script("evaluate.py"),
    "tts": lambda: script("pregenerate_tts.py"),
    "api": lambda: run(PY, "-m", "uvicorn", "vrikka.api.main:app", "--port", "8000"),
    "app": lambda: run(PY, "-m", "streamlit", "run", "app/Home.py", "--server.port", "8501"),
    "demo": demo,
    "test": lambda: run(PY, "-m", "pytest", "-m", "not slow and not data and not net"),
    "test-all": lambda: run(PY, "-m", "pytest"),
    "lint": lambda: run(PY, "-m", "ruff", "check", "."),
}
TARGETS["all"] = lambda: [TARGETS[t]() for t in ("data", "validate-db", "cohort", "features", "train", "eval")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", choices=sorted(TARGETS))
    for t in ap.parse_args().targets:
        TARGETS[t]()


if __name__ == "__main__":
    main()
