"""Build the real-data validation database (master plan §15.1 R1a/R1b, §24).

Loads the MIMIC-IV Clinical Database Demo and the eICU-CRD Demo into data/raw/validation.duckdb, then runs the
official mimic-code DuckDB concept SQL (MIT licence, vendored in scripts/sql/mimic_code/) in dependency order to
build mimiciv_derived.kdigo_creatinine and mimiciv_derived.kdigo_stages. Our own kdigo_stage() is compared with
these tables in Part 4 (R1a).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb

from vrikka.config import DATA_DIR, REPORTS_DIR

RAW = DATA_DIR / "raw"
DB = RAW / "validation.duckdb"
SQL_DIR = Path(__file__).resolve().parent / "sql" / "mimic_code"
# mimic-code concepts needed for KDIGO staging, in dependency order.
CONCEPTS = ["weight_durations", "urine_output", "crrt", "kdigo_creatinine", "kdigo_uo", "kdigo_stages"]


def find_dir(root: Path, name: str) -> Path:
    hits = [p for p in root.rglob(name) if p.is_dir()]
    if not hits:
        raise FileNotFoundError(f"no '{name}' folder under {root}; run scripts/download_public_data.py first")
    return hits[0]


def load_tables(con: duckdb.DuckDBPyConnection, schema: str, folder: Path) -> dict[str, int]:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    counts = {}
    for f in sorted(folder.glob("*.csv.gz")):
        table = f.name.removesuffix(".csv.gz")
        con.execute(f"CREATE OR REPLACE TABLE {schema}.{table} AS "
                    f"SELECT * FROM read_csv_auto('{f.as_posix()}', header=true, sample_size=-1)")
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0]
    return counts


def main() -> int:
    t0 = time.time()
    con = duckdb.connect(str(DB))
    mimic_root = RAW / "mimic_iv_demo"
    hosp = load_tables(con, "mimiciv_hosp", find_dir(mimic_root, "hosp"))
    icu = load_tables(con, "mimiciv_icu", find_dir(mimic_root, "icu"))
    print(f"MIMIC-IV demo: {len(hosp)} hosp tables, {len(icu)} icu tables loaded", flush=True)

    con.execute("CREATE SCHEMA IF NOT EXISTS mimiciv_derived")
    derived = {}
    for name in CONCEPTS:
        con.execute((SQL_DIR / f"{name}.sql").read_text(encoding="utf-8"))
        derived[name] = con.execute(f"SELECT COUNT(*) FROM mimiciv_derived.{name}").fetchone()[0]
        print(f"  mimiciv_derived.{name}: {derived[name]:,} rows", flush=True)

    eicu_dir = RAW / "eicu_crd_demo"
    eicu_folder = next((p.parent for p in eicu_dir.rglob("patient.csv.gz")), None)
    eicu = load_tables(con, "eicu", eicu_folder) if eicu_folder else {}
    print(f"eICU-CRD demo: {len(eicu)} tables loaded", flush=True)

    stats = {
        "mimic_patients": con.execute("SELECT COUNT(DISTINCT subject_id) FROM mimiciv_hosp.patients").fetchone()[0],
        "mimic_icu_stays": con.execute("SELECT COUNT(*) FROM mimiciv_icu.icustays").fetchone()[0],
        "mimic_creatinine_measurements": con.execute(
            "SELECT COUNT(*) FROM mimiciv_hosp.labevents WHERE itemid = 50912 AND valuenum IS NOT NULL").fetchone()[0],
        "kdigo_stays_with_creatinine_stage": con.execute(
            "SELECT COUNT(DISTINCT stay_id) FROM mimiciv_derived.kdigo_stages "
            "WHERE aki_stage_creat IS NOT NULL").fetchone()[0],
        "kdigo_creatinine_stage_counts": dict(con.execute(
            "SELECT aki_stage_creat, COUNT(*) FROM mimiciv_derived.kdigo_stages "
            "WHERE aki_stage_creat IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()),
    }
    if eicu:
        stats["eicu_patient_stays"] = eicu.get("patient")
        stats["eicu_creatinine_measurements"] = con.execute(
            "SELECT COUNT(*) FROM eicu.lab WHERE labname = 'creatinine' AND labresult IS NOT NULL").fetchone()[0]
    con.close()
    for k, v in stats.items():
        print(f"{k}: {v}")

    inv_path = REPORTS_DIR / "data_inventory.json"
    inv = json.loads(inv_path.read_text()) if inv_path.exists() else {}
    inv["validation_duckdb"] = {
        "path": "data/raw/validation.duckdb (gitignored)", "mimic_tables": {**hosp, **icu},
        "eicu_tables": eicu, "mimic_code_derived": derived,
        "stats": {k: ({str(a): b for a, b in v.items()} if isinstance(v, dict) else v) for k, v in stats.items()},
        "build_seconds": round(time.time() - t0, 1),
    }
    inv_path.write_text(json.dumps(inv, indent=2), encoding="utf-8")
    print(f"\nbuilt {DB.name} in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
