# Data: sources, licences, and what is (not) committed

VrikkaTwin uses **only synthetic, open or anonymised data**. No real patient data is used anywhere. Large or
share-alike datasets are **not committed**: `scripts/download_public_data.py` fetches them into `data/raw/`
(gitignored), and prints each licence before downloading.

| Source | Used for | Licence | In this repo? |
|---|---|---|---|
| Our synthetic cohort (`scripts/generate_cohort.py`, enriched high-risk heat-season cohort, 3,000 patients x 3 seasons) | Training and evaluation | MIT (ours) | 20-patient sample (`data/synthetic/sample/`) + generator (deterministic, seed 42) |
| Open-Meteo historical weather (ERA5), 7 Indian cities, 1 Mar to 30 Jun of 2024 (training), 2025 and 2026 (held-out test) | Heat exposure replay | CC BY 4.0, "Weather data by Open-Meteo.com" | Yes, `data/weather/*.parquet` (see `ATTRIBUTION.md`) |
| MIMIC-IV Clinical Database Demo v2.2 (PhysioNet) | KDIGO labelling check (R1a), creatinine kinetics (R1b) | ODbL v1.0 (open access) | No: download script only (share-alike) |
| eICU-CRD Demo v2.0.1 (PhysioNet) | Creatinine kinetics, second cohort (R1b) | ODbL v1.0 (open access) | No: download script only |
| mimic-code KDIGO SQL (MIT-LCP) | Reference KDIGO stages | MIT | Yes, vendored in `scripts/sql/mimic_code/` |
| UCI Chronic Kidney Disease (400 patients; hospital, city and country not stated on the UCI page) | R2 plausibility overlay of lab distributions (no pass/fail claim) | CC BY 4.0 | No: download script only |
| Tawam CKD cohort (Al-Shamsi et al., PLoS ONE 2018, S2 data, 491 patients) | Slow-clock risk ranking (R3) | CC BY 4.0 | No: download script only |
| PMData (Simula; 16 people; raw Fitbit heart rate + self-reported weight) | R4: measured resting-HR noise (`sigma_hr_bpm` = 4.04 bpm); false-alarm check as a secondary line | CC BY 4.0 | No: download script only (raw heart rate ~1 GB) |
| Circadian Timing and Heat Stress in Firefighters (Mendeley 7ghxcsd9sz) | R5 dropped: outside ISO 7933 validity (PPE, > 50 °C) | CC BY 4.0 | No |

**Assessed and not used** (details in `docs/DATA_SEARCH.md`): BD-KDD (values look synthetic), OSF dm3qf (no licence), CGMacros.

**Refused on purpose:** full MIMIC-IV and full eICU-CRD (they need PhysioNet credentialing).

Genotypes (CYP2C9) in the synthetic cohort are simulated from published Indian allele frequencies; no real
genetic data is used.
