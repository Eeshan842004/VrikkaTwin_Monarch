"""Gate G1 data checks (master plan §27 P1). Marked `data`: they need downloads, so CI skips them."""
import pandas as pd
import pytest

from vrikka.config import DATA_DIR, load_yaml

pytestmark = pytest.mark.data
CITIES = list(load_yaml("cities"))
SEASONS = [2024, 2025, 2026]   # 2024 = training season; 2025 and 2026 = held-out test seasons (Decisions v1)


def weather(year, city):
    return pd.read_parquet(DATA_DIR / "weather" / str(year) / f"{city}.parquet")


@pytest.mark.parametrize("year", SEASONS)
@pytest.mark.parametrize("city", CITIES)
def test_weather_parquet_complete(year, city):
    df = weather(year, city)
    assert len(df) == 122 * 24, "one row per hour, 1 Mar - 30 Jun"
    assert df["time"].min().year == year
    cols = ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "wind_speed_10m", "shortwave_radiation"]
    assert df[cols].notna().all().all()
    assert df["temperature_2m"].between(5, 52).all()
    assert df["relative_humidity_2m"].between(0, 100).all()
    assert (df["wind_speed_10m"] >= 0).all() and (df["shortwave_radiation"] >= 0).all()


def test_heat_season_is_hot_where_expected():
    tmax = {c: weather(2024, c)["temperature_2m"].max() for c in CITIES}
    assert tmax["Delhi"] >= 44 and tmax["Nagpur"] >= 44, "2024 north/central India heatwave"
    assert tmax["Bengaluru"] < tmax["Delhi"], "Bengaluru is the milder control city"


def test_validation_db_has_mimic_code_kdigo_tables():
    duckdb = pytest.importorskip("duckdb")
    db = DATA_DIR / "raw" / "validation.duckdb"
    if not db.exists():
        pytest.skip("run scripts/build_validation_duckdb.py first")
    con = duckdb.connect(str(db), read_only=True)
    try:
        n_cr = con.execute("SELECT COUNT(*) FROM mimiciv_derived.kdigo_creatinine").fetchone()[0]
        n_st = con.execute("SELECT COUNT(*) FROM mimiciv_derived.kdigo_stages").fetchone()[0]
    finally:
        con.close()
    assert n_cr > 0 and n_st > 0
