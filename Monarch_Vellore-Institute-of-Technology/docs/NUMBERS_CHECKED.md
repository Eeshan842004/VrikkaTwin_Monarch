# Numbers checked

Every external fact that the README, slides or video may quote, with its source and who checked it. **Slides and the
video quote only rows marked "supported".** Our own results are not listed one by one: they are read directly from
`reports/*.json` (the app and the slide generator load the files; nothing is typed by hand), and the scripts that
write them are named in `PROGRESS.md`.

Checked on 18 Oct 2026 by Claude (AI assistant working for the team), against the publisher's page or an
indexed copy of it. A team member should re-open the "partly supported" rows before quoting them.

| # | Fact | Number used | Source | Status |
|---|---|---|---|---|
| 1 | Triple whammy (diuretic + ACEi/ARB + NSAID) and AKI in antihypertensive users | rate ratio 1.31 (95 % CI 1.12-1.53); 1.82 (1.35-2.46) in the first 30 days; 487,372 people | Lapi F. et al., BMJ 2013;346:e8525. https://www.bmj.com/content/346/bmj.e8525 | supported |
| 2 | SGLT2 inhibitor chronic eGFR slope benefit (EMPA-KIDNEY) | 1.37 mL/min/1.73 m² per year (95 % CI 1.16-1.59) | EMPA-KIDNEY Collaborative Group, Lancet Diabetes Endocrinol 2024;12:51-60 (prespecified analysis; trial NEJM 2023). https://doi.org/10.1016/S2213-8587(23)00322-4 | supported (the figure is in the Lancet D&E analysis, not the NEJM primary paper; registry source corrected) |
| 3 | Heatstroke surveillance, India 2024 | 67,637 suspected cases and 374 deaths, 1 Mar - 27 Jul 2024 (NCDC; Lok Sabha reply) | https://www.dtnext.in/news/national/heatstroke-took-374-lives-till-jul-27-health-ministry-797813 | supported |
| 4 | Intercurrent AKI and eGFR loss in diabetic kidney disease (Trichy) | 1.83 mL/min/year excess loss, p = 0.002, no CI; n = 274; mean follow-up 3.3 y; cohort mean slope -6.43 (-7.02 to -5.84) | Sathiavageesan S. et al., Indian J Nephrol 2025;35:691-3. https://indianjnephrol.org/determinants-of-kidney-function-decline-and-rapid-progression-in-diabetic-kidney-disease/ | supported ("associated with"; single-centre, retrospective) |
| 5 | Cross-shift AKI in Guatemalan sugarcane workers | cumulative incidence 53 % (Feb), 54 % (Mar), 51 % (Apr); 517 workers | Butler-Dawson J. et al., Int Arch Occup Environ Health 2019;92:977-990. https://stacks.cdc.gov/view/cdc/213347 | supported |
| 6 | Mean cross-shift eGFR fall in sugarcane workers | 21.8 % (SD 13.6 %); 105 workers | Sorensen C.J. et al., J Occup Environ Med 2019. https://stacks.cdc.gov/view/cdc/217396 | supported |
| 7 | GFR fall in a mountain ultramarathon | GFR to 0.7-fold of 89 ml/min/1.73 m² by 84 km, then a plateau; 6 runners | Belli T. et al., Front Physiol 2018;9:1368. https://doi.org/10.3389/fphys.2018.01368 | partly supported: the GFR fall is confirmed; the pairing with 3.7 % / > 5 % body-mass loss used for L5 was not found in the text checked |
| 8 | Heat and renal hospital admissions, Brazil | +0.9 % risk per 1 °C (lag 0-7 days); 2,726,886 admissions, 1,816 cities, 2000-2015 | Wen B. et al., Lancet Regional Health - Americas 2021. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9903579/ | supported |
| 9 | SGLT2 inhibitors and AKI | RR 0.78 (95 % CI 0.71-0.84); 18 RCTs, 98,989 patients | Frontiers in Pharmacology 2024 meta-analysis. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11231204/ | supported |
| 10 | WHO reduced-osmolarity ORS | Na 75, Cl 65, glucose 75, K 20, citrate 10 mmol/L; 245 mOsm/L | WHO Drug Information 2002. https://www.rehydrate.org/ors/newformula-studies.html | supported |
| 11 | Sick-day guidance needs individual risk-benefit; harms possible without clinical assessment | qualitative | Think Kidneys position statement 2018. https://www.thinkkidneys.nhs.uk/aki/news/sick-day-statement/ | supported (our badge paraphrases it: "individualised, weak evidence, clinician decides") |
| 12 | Heatstroke definition used by the red flags | core temperature 40 °C or higher with CNS dysfunction | NCDC National Action Plan on Heat Related Illnesses. https://ncdc.mohfw.gov.in/wp-content/uploads/2024/05/1.Nation-Action-plan-on-Heat-Related-llnesses.pdf | supported (as quoted in `config/red_flags.yaml`) |
| 13 | KFRE 4-variable, non-North-American baseline survival | 0.9832 (2 y), 0.9365 (5 y) | Tangri N. et al., JAMA 2016; checked against the `kfre` 0.1.18 package to 1e-6 (`tests/test_equations.py`) | supported (by test) |
| 14 | CKD-EPI 2021 race-free equation | golden values 64.5 / 73.7 | Inker L.A. et al., NEJM 2021; `tests/test_equations.py` | supported (by test) |
| 15 | KDIGO creatinine criteria | rise >= 0.3 mg/dL within 48 h, or >= 1.5x baseline within 7 days | KDIGO 2012 AKI guideline; agreement with the official mimic-code SQL in `reports/r1_validation.json` | supported |
| 16 | Datasets | MIMIC-IV demo 100 patients; eICU demo; UCI CKD 400 rows; Tawam 491 patients; PMData 16 people | `reports/data_inventory.json`, `reports/r3_tawam.json`, `reports/r4_pmdata.json` (counted from the files) | supported (by the data) |

Not verified and therefore **not quoted** in slides: the Belli body-mass pairing (row 7) and any number in the plan files
that is not in this table.
