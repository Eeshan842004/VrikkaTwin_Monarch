# VrikkaTwin build log

Team Monarch, Vellore Institute of Technology. The build follows the team's design plan in 8 parts, with a stop after each part. Every entry records what was built, the test results, key numbers (with their source file), decisions, deviations from the plan, open issues and commit hashes.

| Part | Phases | Gate | Status |
|---|---|---|---|
| 1 Foundation | P0 + P1 | G0, G1 | in progress |
| 2 Physiology engine | P2 | G2 | not started |
| 3 Twin + synthetic world | P3 ‖ P4 | exit checks | not started |
| 4 Fast clock | P5 | G3 | not started |
| 5 Slow clock + what-if | P6 + P7 | exit checks | not started |
| 6 Backend + trust layer | P8 | G4 | not started |
| 7 Frontend + evaluation | P9 ‖ P10 | G5 freeze | not started |
| 8 Deliverables + submission | P11 | G6 | not started |

---

## Part 1: Foundation (P0 + P1)

_Started Wed 14 Oct 2026, 19:30 IST._

### Decisions and deviations
- **Python 3.12, not 3.11.** `shap==0.53.0` (a pinned §17 version) requires Python ≥3.12. The plan lists 3.12 as acceptable, so the venv uses CPython 3.12.14. All other §17 pins resolved at their exact versions.
- **Team folder name** `Monarch_Vellore-Institute-of-Technology` (hyphens instead of spaces so paths and URLs stay safe).
- **CI workflow at the repo root** (`.github/workflows/ci.yml`, `working-directory` = team folder), because GitHub only runs workflows from the repository root.
- **`tasks.py` mirrors the Makefile**, because `make` is not installed on the Windows build machine.
- **Drug effect half-lives are per drug** in the registry (HCTZ 12 h, chlorthalidone 48 h, indapamide 24 h [new ASSUMPTION], loop 6 h), replacing the single hard-coded 48 h diuretic value in the plan's twin snippet.
- **New registry ASSUMPTIONS not in the plan's table** (each with a range): `half_life_indapamide_h`, `sigma_sbp_mmhg`, `indoor_offset_thatch_c`, `indoor_offset_cooler_c`.
- **Fever is always "°C above 37"** everywhere in the registry and code.
