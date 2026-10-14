# Vendored mimic-code SQL

These DuckDB concept scripts are copied unchanged from
[MIT-LCP/mimic-code](https://github.com/MIT-LCP/mimic-code) (`mimic-iv/concepts_duckdb/`), MIT licence
(see `LICENSE_mimic-code.txt`). `scripts/build_validation_duckdb.py` runs them on the MIMIC-IV demo to produce
the reference KDIGO stages that our own `kdigo_stage()` is checked against (validation R1a).

| File | Upstream path |
|---|---|
| `weight_durations.sql` | `demographics/weight_durations.sql` |
| `urine_output.sql` | `measurement/urine_output.sql` |
| `crrt.sql` | `treatment/crrt.sql` |
| `kdigo_creatinine.sql` | `organfailure/kdigo_creatinine.sql` |
| `kdigo_uo.sql` | `organfailure/kdigo_uo.sql` |
| `kdigo_stages.sql` | `organfailure/kdigo_stages.sql` |
