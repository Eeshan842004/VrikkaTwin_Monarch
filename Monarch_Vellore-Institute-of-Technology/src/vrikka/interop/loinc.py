"""LOINC codes for the observations VrikkaTwin exchanges (FHIR export; simulator/devices uses the same weight code)."""
from __future__ import annotations

LOINC = {
    "creatinine_mg_dl": ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL"),
    "egfr": ("98979-8", "Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] in Serum, Plasma or Blood "
                        "by Creatinine-based formula (CKD-EPI 2021)", "mL/min/{1.73_m2}"),
    "uacr_mg_g": ("9318-7", "Albumin/Creatinine [Mass Ratio] in Urine", "mg/g{creat}"),
    "potassium_mmol_l": ("2823-3", "Potassium [Moles/volume] in Serum or Plasma", "mmol/L"),
    "weight_kg": ("29463-7", "Body weight", "kg"),
    "resting_hr_bpm": ("40443-4", "Heart rate --resting", "/min"),
    "sbp_mmhg": ("8480-6", "Systolic blood pressure", "mm[Hg]"),
    "temperature_c": ("8310-5", "Body temperature", "Cel"),
    "steps": ("55423-8", "Number of steps in unspecified time Pedometer", "{steps}"),
}
