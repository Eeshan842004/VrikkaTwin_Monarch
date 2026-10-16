# Math context: symbols, units and assumptions (VrikkaTwin)

v0.2, 16 Oct 2026. v0.1 was generated from the design plan (§8–§13) for an independent maths check; v0.2 brings it in
line with the code after the 16 Oct engine revision. Changes from v0.1 are listed at the end.

## Symbols (all real, non-negative unless stated)
- W: body weight (kg) > 0. TBW: total body water (L) = f_tbw·W, f_tbw ∈ {0.45 (F), 0.50 (M)}, +0.05 if age < 60.
- ECV0 = ecv_frac·W (L), ecv_frac = 0.20.
- v_tot(t), v_ecf(t): total and extracellular water deficits (L), 0 ≤ v_ecf ≤ v_tot.
- d = v_ecf/ECV0 (dimensionless) ≥ 0.
- h(d) = dⁿ/(dⁿ + d50ⁿ), n = hill_n > 0, d50 > 0.
- prot = a_tot·[s(1−I_PG) + (1−s)(1−I_RAS·r)] with a_tot, s, I_PG, I_RAS, r ∈ [0,1].
- ex(t) ∈ [0,1]: lagged exertion fraction, the first-order lag (τ_ex) of clip((met(t) − met_thr)/met_span, 0, 1).
- GFR (mL/min) = GFR_base·[1 − h(d)(1 − prot)]·(1 − k_ex·ex), with k_ex ∈ [0,1).
- Cr: serum creatinine (mg/dL) > 0. G: creatinine generation (mg/min) = GFR_base·Cr_base/100.
- Vd(t): creatinine distribution volume (dL) = 10·max(TBW − v_tot(t), vd_floor·TBW), vd_floor = 0.8. M = Cr·Vd:
  creatinine mass (mg).
- Time t in minutes for kinetics unless stated (the code steps one hour at a time).
- eGFR: mL/min/1.73 m² (CKD-EPI 2021). KFRE: probability ∈ (0,1). ACR in mg/g.
- KDIGO creatinine criteria, applied to one 08:00 value per day: AKI if Cr(t) − min Cr over the previous 48 h ≥ 0.3
  mg/dL, or Cr(t)/baseline ≥ 1.5 within 7 days. Baseline = the §9.3 rule (mean of the last 2 stable values within 365
  days, else a single stable value, else back-calculated from eGFR 75). Cr ≥ 4.0 only upgrades an existing AKI.
  Urine-output criteria are not used.
- Slow clock: eGFR_i = a + b·t_i + ε_i, ε_i ~ N(0, σ²); prior (a,b) ~ N(m0, P0⁻¹).
- Prior shift: π = training prevalence, π′ = target prevalence, odds ratio r = [π′/(1−π′)]/[π/(1−π)];
  p′ = p·r/(p·r + 1 − p).

## Creatinine kinetics
Mass balance: dM/dt = G − GFR·Cr/100 with Cr = M/Vd(t), i.e. dCr/dt = (G − GFR·Cr/100)/Vd − Cr·(dVd/dt)/Vd.
Within each hour G and GFR are constant and Vd changes from Vd₀ to Vd₁; the code uses the mean volume
V̄ = (Vd₀ + Vd₁)/2 for clearance:
1. rescale to the mean volume, Cr ← Cr·Vd₀/V̄;
2. apply the exact exponential step, Cr ← Css + (Cr − Css)·exp(−0.6·GFR·Δt_h/V̄), with Css = 100·G/GFR;
3. rescale to the new volume, Cr ← Cr·V̄/Vd₁.

With a constant volume this is the exact solution of the original equation. The time constant is
τ = 100·Vd/GFR minutes (5.0 h at GFR 100 / TBW 30 L; 9.1 h at GFR 55).

## Global assumptions
- Single-compartment creatinine kinetics; creatinine distributes in total body water; no change in tubular secretion
  in the twin (the truth simulator adds co-trimoxazole and exertional muscle breakdown as hidden causes).
- GFR is used as absolute mL/min in the kinetics, while eGFR is BSA-normalised. For a 62 kg / 160 cm woman BSA is
  1.64 m², so absolute GFR ≈ 0.95 × eGFR. Steady state is unaffected (G derives from the same GFR_base); τ shifts
  about 5 %.
- A healthy kidney on no drugs loses at most 1 − a_tot of its GFR to dehydration (20 % when young), so in the twin
  dehydration alone cannot cause AKI in that person. Real severe dehydration (shock, heatstroke) can; the red-flag
  emergency rules cover it and override the model.
- Hourly time step; inputs are constant within each hour.

## Changes from v0.1
- **Integration:** v0.1 said "Euler integration with Δt = 60 min". The code has always used the exact exponential
  update within each hour (the Euler form had a maximum relative error of 1.6 % over 72 h).
- **KDIGO baseline:** v0.1 said "min over prior 7 days unless given". The code, the labels and the twin all use the
  §9.3 baseline rule above, with one 08:00 value per day.
- **Added** after the 16 Oct engine revision (Decisions v5 C1, C2):
  - the time-varying distribution volume and the mass-conserving kinetics. The v4 idea of simply shrinking Vd inside
    the old equation has no concentration effect;
  - the exertion factor (1 − k_ex·ex).
