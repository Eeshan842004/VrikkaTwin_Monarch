# Data search: what exists, what we use, and what does not exist openly

_Last updated 16 Oct 2026._

**In one sentence:** real data for this exact problem does not exist openly, so we built a simulator from published evidence, kept it separate from the model, and checked every component we could against real data.

## Where we searched

PhysioNet, Zenodo, figshare, Dryad, Mendeley Data, OSF, Kaggle, data.gov.in, the UCI repository, and the published literature on heat, dehydration, drugs and kidney function.

## What we use, and why

| Source | What it gives us | Used for | Licence | In the repo? |
|---|---|---|---|---|
| Open-Meteo / ERA5 weather, 7 Indian cities, Mar–Jun 2024, 2025, 2026 | Hourly heat exposure | Heat → sweat; 2024 = training season, 2025 and 2026 = held-out test seasons | CC BY 4.0 | Yes |
| MIMIC-IV Clinical Database Demo v2.2 (+ mimic-code KDIGO SQL) | Real ICU creatinine series and the official KDIGO staging | R1a: our labelling checked against the official code; R1b: our creatinine equation vs real patients | ODbL (open) / MIT | Download script only |
| eICU-CRD Demo v2.0.1 | A second real creatinine cohort | R1b | ODbL (open) | Download script only |
| UCI CKD dataset (origin not verifiable from the source page; 400 patients) | Real lab values (creatinine, urea, haemoglobin, sodium, potassium) | R2: plausibility overlay of our cohort's labs (no pass/fail claim). The UCI page does not name the hospital, city or country, so we do not state a site | CC BY 4.0 | Download script only |
| Tawam CKD cohort (Al-Shamsi et al., PLoS ONE 2018, 491 patients) | Baseline values + time to CKD stage 3 | R3: slow-clock risk ranking vs baseline eGFR alone | CC BY 4.0 | Download script only |
| PMData (16 people; raw Fitbit heart rate, self-reported weight) | Real day-to-day noise | R4: measured resting-HR noise → `sigma_hr_bpm` = 4.04 bpm | CC BY 4.0 | Download script only |

## Assessed and not used

| Candidate | Why not used |
|---|---|
| **BD-KDD** (Zenodo 18971931, 2026; 988 records from a Bangladesh diagnostic centre) | The values do not behave like real lab data: 92.7 % of the "healthy" group have serum creatinine > 1.5 mg/dL (median 7.1 mg/dL); creatinine is uncorrelated with urea (r = 0.005; 0.59 in UCI CKD) and with the disease label (r = 0.03); most columns are statistically indistinguishable from flat uniform distributions between round limits. The source institution's permission letter also restricts use to one approved academic purpose. A download script is kept so this check can be reproduced. |
| OSF project dm3qf ("POC and Serum Creatinine", Guatemala heat workers; 194 paired serum vs point-of-care creatinine values) | **NOT AVAILABLE:** no licence is declared, so the data may not be reused. Inspected for structure only; not stored. |
| CGMacros | About 10 days per person, no kidney labs, non-commercial share-alike licence; PMData already covers heart-rate noise. |
| Firefighter heat study (Mendeley 7ghxcsd9sz) | Considered; outside ISO 7933 validity (protective equipment, > 50 °C). |
| "Kidney Function Health" (Kaggle) | Synthetic; synthetic-vs-synthetic validates nothing. |
| Calf dehydration dataset (Dryad) | Bovine; not used in a human clinical project. |
| NephTox | Covers anti-cancer agents only, not NSAIDs, ACE inhibitors, ARBs or diuretics. |
| Boston Marathon 2019 creatinine paper | No pre-race values and cool weather (WBGT ~18 °C), so recovery cannot be calibrated. |
| Mechanistic "triple whammy" kidney model (Leete & Layton, Math Biosci 2022) | No public code. Our reduced model is *inspired by* it; we do not claim to reimplement it. |

## Literature used as calibration targets (bands, not tuning targets)

| ID | Evidence | How we use it |
|---|---|---|
| L1 | Lapi et al., BMJ 2013 (n = 487,372): triple therapy RR 1.31 overall, 1.82 in the first 30 days | Triple vs double therapy within antihypertensive users; band 1.1–2.5 |
| L2 | Brazil, 2.7 M renal admissions: +0.9 % per °C | Loose sanity check (hospital admissions vs our mild AKI) |
| L3 | Trichy diabetic kidney disease cohort (n = 274): −1.83 mL/min/yr per AKI | Slow-clock penalty, labelled "from a diabetic cohort" |
| L4 | Butler-Dawson et al. 2019 (n = 517 cane cutters): cross-shift AKI ~50 % per month; Sorensen et al. 2019: mean cross-shift eGFR fall 21.8 % | Intra-day creatinine in a heavy outdoor worker |
| L5 | Belli et al. 2018 (n = 6 ultramarathon runners): GFR −25–27 % at ~3.7 % body-mass loss, −27–44 % above 5 % | Volume → GFR dose-response sanity check |

## Why the label uses morning creatinine

Transient creatinine rises after a hot shift are very common in heat-exposed workers: about half of heavy cane cutters meet a cross-shift AKI definition in a month (Butler-Dawson 2019). Part of that rise is haemoconcentration, exertion and muscle creatinine release, and some is assay bias in point-of-care tests. Morning (08:00, fasting) values separate a transient rise from sustained injury. That is why VrikkaTwin labels AKI, and advises tests, on morning values.

## What does not exist openly (as of October 2026)

- No dataset links wearables + heat + medicines with **serial outpatient creatinine**.
- No controlled human dehydration study with serial creatinine.
- No Indian outpatient serial-creatinine dataset with genotype.
- No district-level daily heat / kidney-admission data for India.
- No usable open South Asian outpatient creatinine dataset: the one candidate we found (BD-KDD) was examined and not used (see above).
