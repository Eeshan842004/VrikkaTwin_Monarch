"""Download the open datasets used for real-data component checks (master plan §15.1, §24).

Everything lands in data/raw/<name>/ (gitignored). The script prints each dataset's licence before
downloading and refuses credentialed datasets. Nothing from data/raw is ever committed.

    python scripts/download_public_data.py            # all open datasets
    python scripts/download_public_data.py --only uci_ckd tawam
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

import requests

from vrikka.config import DATA_DIR, REPORTS_DIR

RAW = DATA_DIR / "raw"
UA = {"User-Agent": "VrikkaTwin-research-download/0.1 (Team Monarch, VIT)"}

DATASETS = {
    # PhysioNet throttles each connection to a few KB/s, so we fetch only the tables we use, in parallel
    # byte-range chunks (the full zips are 16 MB and 137 MB).
    "mimic_iv_demo": {
        "check": "R1a, R1b", "licence": "Open Data Commons ODbL v1.0 (open access, no credentialing)",
        "url": "https://physionet.org/files/mimic-iv-demo/2.2/", "kind": "physionet_files",
        "files": ["hosp/patients.csv.gz", "hosp/admissions.csv.gz", "hosp/labevents.csv.gz",
                  "hosp/d_labitems.csv.gz", "icu/icustays.csv.gz", "icu/chartevents.csv.gz",
                  "icu/outputevents.csv.gz", "icu/d_items.csv.gz", "LICENSE.txt"],
        "cite": "Johnson A. et al. MIMIC-IV Clinical Database Demo v2.2. PhysioNet.",
    },
    "eicu_crd_demo": {
        "check": "R1b", "licence": "Open Data Commons ODbL v1.0 (open access, no credentialing)",
        "url": "https://physionet.org/files/eicu-crd-demo/2.0.1/", "kind": "physionet_files",
        "files": ["patient.csv.gz", "lab.csv.gz", "LICENSE.txt"],
        "cite": "Johnson A. et al. eICU Collaborative Research Database Demo v2.0.1. PhysioNet.",
    },
    "uci_ckd": {
        "check": "R2", "licence": "CC BY 4.0",
        # The zip wraps a .rar archive; UCI also serves the same table as CSV, which needs no extra tools.
        "url": "https://archive.ics.uci.edu/static/public/336/data.csv", "kind": "file", "filename": "uci_ckd.csv",
        "cite": "Rubini L., Soundarapandian P., Eswaran P. Chronic Kidney Disease. UCI ML Repository (2015).",
    },
    "tawam": {
        "check": "R3", "licence": "CC BY 4.0 (PLOS ONE supporting information)",
        "url": "https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0199920.s002",
        "kind": "file", "filename": "tawam_ckd_S2.xlsx",
        "cite": "Al-Shamsi S., Regmi D., Govender R.D. PLoS ONE 13(6): e0199920 (2018).",
    },
    "firefighter_heat": {
        "check": "R5 (exploratory)", "licence": "CC BY 4.0",
        "url": "https://data.mendeley.com/public-api/datasets/7ghxcsd9sz", "kind": "mendeley",
        "cite": "Circadian Timing and Heat Stress in Firefighters. Mendeley Data 7ghxcsd9sz.",
    },
    "pmdata": {
        "check": "R4", "licence": "CC BY 4.0",
        "url": "https://api.osf.io/v2/nodes/vx4bk/files/osfstorage/", "kind": "osf_subset",
        "cite": "Thambawita V. et al. PMData: a sports logging dataset. MMSys 2020.",
        "subset": {  # small per-participant files only (the full zip is 1.4 GB)
            "fitbit": ["resting_heart_rate.json", "sleep_score.csv", "very_active_minutes.json",
                       "moderately_active_minutes.json", "lightly_active_minutes.json", "sedentary_minutes.json"],
            "googledocs": ["reporting.csv"],
            "pmsys": ["wellness.csv"],
        },
    },
}
REFUSED = {
    "mimic_iv_full": "needs PhysioNet credentialing (1-2 weeks per member); master plan §24 says do not use",
    "eicu_crd_full": "needs PhysioNet credentialing; master plan §24 says do not use",
}


def get(url: str, **kw) -> requests.Response:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            print(f"    retry ({exc})", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def save_stream(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(5):
        try:
            with requests.get(url, headers=UA, timeout=300, stream=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            tmp.replace(dest)
            return dest.stat().st_size
        except requests.RequestException as exc:
            if attempt == 4:
                raise
            print(f"    retry {dest.name} ({exc})", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def save_ranged(url: str, dest: Path, workers: int = 16, chunk: int = 256 * 1024) -> int:
    """Download one file as parallel HTTP byte-range chunks (for slow per-connection servers)."""
    if dest.exists():
        return dest.stat().st_size
    head = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
    head.raise_for_status()
    size = int(head.headers.get("Content-Length", 0))
    if size <= chunk:
        return save_stream(url, dest)
    ranges = [(s, min(s + chunk, size) - 1) for s in range(0, size, chunk)]

    def fetch(rng: tuple[int, int]) -> tuple[int, bytes]:
        for attempt in range(6):
            try:
                r = requests.get(url, headers={**UA, "Range": f"bytes={rng[0]}-{rng[1]}"}, timeout=300)
                if r.status_code == 206 and len(r.content) == rng[1] - rng[0] + 1:
                    return rng[0], r.content
            except requests.RequestException:
                pass
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"range {rng} failed for {url}")

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(workers) as ex:
        parts = dict(ex.map(fetch, ranges))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with tmp.open("wb") as fh:
        for start, _ in ranges:
            fh.write(parts[start])
    tmp.replace(dest)
    if dest.stat().st_size != size:
        raise RuntimeError(f"size mismatch for {url}")
    return size


def osf_list(url: str) -> list[dict]:
    items = []
    while url:
        js = get(url).json()
        items += js["data"]
        url = js["links"].get("next")
    return items


def download(name: str, spec: dict) -> dict:
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if spec["kind"] == "zip":
        z = out / f"{name}.zip"
        if not z.exists():
            save_stream(spec["url"], z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(out)
            files = [n for n in zf.namelist() if not n.endswith("/")]
    elif spec["kind"] == "physionet_files":
        for rel in spec["files"]:
            save_ranged(spec["url"] + rel, out / rel)
            files.append(rel)
            print(f"    {rel}: done", flush=True)
    elif spec["kind"] == "file":
        f = out / spec["filename"]
        if not f.exists():
            save_stream(spec["url"], f)
        files = [f.name]
    elif spec["kind"] == "mendeley":
        meta = get(spec["url"]).json()
        for fm in meta.get("files", []):
            f = out / fm["filename"]
            if not f.exists():
                save_stream(fm["content_details"]["download_url"], f)
            files.append(f.name)
    elif spec["kind"] == "osf_subset":
        root = osf_list(spec["url"])
        pm = next(x for x in root if x["attributes"]["name"] == "pmdata")
        for person in osf_list(pm["relationships"]["files"]["links"]["related"]["href"]):
            pid = person["attributes"]["name"]
            if person["attributes"]["kind"] != "folder":   # e.g. an overview spreadsheet next to p01..p16
                if pid.lower().endswith((".xlsx", ".csv", ".txt", ".md")):
                    dest = out / pid
                    if not dest.exists():
                        save_stream(person["links"]["download"], dest)
                    files.append(pid)
                continue
            for folder in osf_list(person["relationships"]["files"]["links"]["related"]["href"]):
                fname = folder["attributes"]["name"]
                if folder["attributes"]["kind"] != "folder" or fname not in spec["subset"]:
                    continue
                for f in osf_list(folder["relationships"]["files"]["links"]["related"]["href"]):
                    if f["attributes"]["name"] in spec["subset"][fname]:
                        dest = out / pid / fname / f["attributes"]["name"]
                        if not dest.exists():
                            save_stream(f["links"]["download"], dest)
                        files.append(f"{pid}/{fname}/{f['attributes']['name']}")
            print(f"    {pid}: done", flush=True)
    (out / "LICENCE.txt").write_text(f"{spec['licence']}\n\nCite: {spec['cite']}\nSource: {spec['url']}\n",
                                     encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    return {"status": "ok", "files": len(files), "bytes": size, "licence": spec["licence"],
            "check": spec["check"], "source": spec["url"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=sorted(DATASETS))
    names = ap.parse_args().only or list(DATASETS)
    print("Refused (credentialed):", "; ".join(f"{k}: {v}" for k, v in REFUSED.items()), "\n")
    inv_path = REPORTS_DIR / "data_inventory.json"
    inv = json.loads(inv_path.read_text()) if inv_path.exists() else {}
    inv.setdefault("datasets", {})
    failed = []
    for name in names:
        spec = DATASETS[name]
        print(f"[{name}] for {spec['check']} | licence: {spec['licence']}", flush=True)
        try:
            res = download(name, spec)
            print(f"    ok: {res['files']} files, {res['bytes'] / 1e6:.1f} MB", flush=True)
        except Exception as exc:  # recorded as a manual step, never silently skipped
            res = {"status": "FAILED - manual download needed", "error": str(exc), "source": spec["url"],
                   "licence": spec["licence"], "check": spec["check"]}
            failed.append(name)
            print(f"    FAILED: {exc}", flush=True)
        inv["datasets"][name] = res
    inv["refused"] = REFUSED
    inv_path.write_text(json.dumps(inv, indent=2), encoding="utf-8")
    print("\nall downloads ok" if not failed else f"\nmanual steps needed for: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
