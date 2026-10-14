# Data: sources, licences, and what is (not) committed

VrikkaTwin uses **only synthetic, open or anonymised data**. No real patient data is used anywhere. Large or
share-alike datasets are **not committed**: `scripts/download_public_data.py` fetches them into `data/raw/`
(gitignored), and prints each licence before downloading.

| Source | Used for | Licence | In this repo? |
|---|---|---|---|
| Our synthetic cohort (`scripts/generate_cohort.py`) | Training and evaluation | MIT (ours) | Small sample + generator |
| Open-Meteo historical weather (ERA5), 7 Indian cities, 1 Mar to 30 Jun 2024 | Heat exposure replay | CC BY 4.0, "Weather data by Open-Meteo.com" | Yes, `data/weather/*.parquet` (see `ATTRIBUTION.md`) |
| MIMIC-IV Clinical Database Demo v2.2 (PhysioNet) | KDIGO labelling check (R1a), creatinine kinetics (R1b) | ODbL v1.0 (open access) | No: download script only (share-alike) |
| eICU-CRD Demo v2.0.1 (PhysioNet) | Creatinine kinetics, second cohort (R1b) | ODbL v1.0 (open access) | No: download script only |
| mimic-code KDIGO SQL (MIT-LCP) | Reference KDIGO stages | MIT | Yes, vendored in `scripts/sql/mimic_code/` |
| UCI Chronic Kidney Disease (400 patients) | Lab-distribution check of the synthetic cohort (R2) | CC BY 4.0 | No: download script only |
| Tawam CKD cohort (Al-Shamsi et al., PLoS ONE 2018, S2 data, 491 patients) | Slow-clock risk ranking (R3) | CC BY 4.0 | No: download script only |
| PMData (Simula; Fitbit + self-reported data) | Real-world false-alarm check (R4) | CC BY 4.0 | No: small per-participant subset downloaded |
| Circadian Timing and Heat Stress in Firefighters (Mendeley 7ghxcsd9sz) | Exploratory sweat check (R5) | CC BY 4.0 | No: download script only |

**Refused on purpose:** full MIMIC-IV and full eICU-CRD (they need PhysioNet credentialing).

Genotypes (CYP2C9) in the synthetic cohort are simulated from published Indian allele frequencies; no real
genetic data is used.
