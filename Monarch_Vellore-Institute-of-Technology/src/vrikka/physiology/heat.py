"""Heat -> sweat: ISO 7933 Predicted Heat Strain via pythermalcomfort, as a cached lookup table (master plan §9.2).

Gotchas (verified with pythermalcomfort 4.6.1):
1. ``met`` is in **met units** (1 met = 58.15 W/m2), not W/m2. Passing 150 gives NaN.
2. The default model "7933-2023" is valid for met 0.96-4.3, tdb 15-50 degC, clo 0.1-1, air speed 0-3 m/s. Many
   hot, humid points are outside it. We call PHS twice: with ``limit_inputs=True`` to get the validity mask and
   with ``limit_inputs=False`` to get extrapolated values, store an ``outside_iso_validity`` flag per point, and cap
   the sweat rate at ``sweat_cap_l_h`` (Decisions v1 item 11).
3. Each hour is computed independently with ``duration=60`` ("memoryless"): heat accumulated in earlier hours does
   not carry over. This is a documented approximation.
4. Air speed is fixed at 0.5 m/s in the table (typical indoor fan / light outdoor breeze).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from vrikka.config import DATA_DIR, param

AIR_SPEED_TABLE_MS = 0.5
DEFAULT_GRID = {
    "tdb": np.arange(15.0, 51.0, 1.0),                                   # degC
    "rh": np.arange(5.0, 101.0, 5.0),                                    # %
    "met": np.array([1.0, 1.2, 1.6, 2.0, 2.5, 3.0, 3.5, 4.0]),            # met units
    "dtr": np.array([0.0, 5.0, 10.0, 15.0]),                             # mean radiant minus air temperature, degC
}


def phs_sweat_l_h(tdb, tr, rh, met, weight_kg: float, height_m: float, clo: float = 0.5,
                  v: float = AIR_SPEED_TABLE_MS, limit_inputs: bool = False) -> np.ndarray:
    """Sweat loss in L over one hour from ISO 7933 PHS (direct call; arrays allowed)."""
    from pythermalcomfort.models import phs  # imported lazily: slow import

    tdb = np.atleast_1d(np.asarray(tdb, dtype=float))
    n = tdb.size
    def full(x):
        return np.broadcast_to(np.asarray(x, dtype=float), (n,)).tolist()
    res = phs(tdb=tdb.tolist(), tr=full(tr), v=[v] * n, rh=full(rh), met=full(met), clo=[clo] * n,
              posture=["standing"] * n, duration=60, weight=weight_kg, height=height_m,
              round_output=False, limit_inputs=limit_inputs)
    return np.asarray(res.sweat_loss_g, dtype=float) / 1000.0


@dataclass
class SweatTable:
    """Interpolated PHS sweat rate (L/h) on a (tdb, rh, met, dtr) grid for one body size and clothing."""

    axes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    sweat: np.ndarray        # L/h, shape (tdb, rh, met, dtr), extrapolated where outside ISO validity
    valid: np.ndarray        # bool, same shape: inside ISO 7933 validity
    weight_kg: float
    height_m: float
    clo: float

    def __post_init__(self) -> None:
        self._interp = RegularGridInterpolator(self.axes, self.sweat, bounds_error=False, fill_value=None)
        self._valid = RegularGridInterpolator(self.axes, self.valid.astype(float), method="nearest",
                                              bounds_error=False, fill_value=None)

    def _points(self, tdb, rh, met, dtr) -> np.ndarray:
        arrs = np.broadcast_arrays(*(np.asarray(a, dtype=float) for a in (tdb, rh, met, dtr)))
        pts = np.stack([a.ravel() for a in arrs], axis=-1)
        lo = np.array([ax[0] for ax in self.axes])
        hi = np.array([ax[-1] for ax in self.axes])
        return np.clip(pts, lo, hi), arrs[0].shape

    def rate(self, tdb, rh, met, dtr, sweat_mult: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        """Sweat rate (L/h, capped at ``sweat_cap_l_h``) and inside-validity flag. Arrays broadcast."""
        pts, shape = self._points(tdb, rh, met, dtr)
        s = np.clip(self._interp(pts) * sweat_mult, 0.0, param("sweat_cap_l_h")).reshape(shape)
        ok = (self._valid(pts) > 0.5).reshape(shape)
        return s, ok


def build_sweat_table(weight_kg: float, height_m: float, clo: float = 0.5,
                      grid: dict[str, np.ndarray] | None = None) -> SweatTable:
    """Run PHS over the whole grid (about a minute for the default grid)."""
    g = grid or DEFAULT_GRID
    axes = (g["tdb"], g["rh"], g["met"], g["dtr"])
    T, R, M, D = (a.ravel() for a in np.meshgrid(*axes, indexing="ij"))
    shape = tuple(len(a) for a in axes)
    valid = ~np.isnan(phs_sweat_l_h(T, T + D, R, M, weight_kg, height_m, clo, limit_inputs=True))
    sweat = phs_sweat_l_h(T, T + D, R, M, weight_kg, height_m, clo, limit_inputs=False)
    if np.isnan(sweat).any():   # PHS can still fail at extreme corners: fill from the nearest finite point
        from scipy.interpolate import NearestNDInterpolator
        ok = ~np.isnan(sweat)
        sweat[~ok] = NearestNDInterpolator(np.c_[T, R, M, D][ok], sweat[ok])(np.c_[T, R, M, D][~ok])
    return SweatTable(axes, np.maximum(sweat, 0.0).reshape(shape), valid.reshape(shape), weight_kg, height_m, clo)


def load_sweat_table(weight_kg: float, height_m: float, clo: float = 0.5,
                     cache_dir: Path | None = None) -> SweatTable:
    """Cached table for a body-size band (weight to 5 kg, height to 0.05 m, clo to 0.1)."""
    w = float(np.clip(5 * round(weight_kg / 5), 35, 120))
    h = round(float(np.clip(0.05 * round(height_m / 0.05), 1.40, 1.95)), 2)
    c = round(clo, 1)
    cache = (cache_dir or DATA_DIR / "cache") / f"sweat_table_w{w:.0f}_h{h:.2f}_c{c:.1f}.npz"
    if cache.exists():
        z = np.load(cache)
        return SweatTable((z["tdb"], z["rh"], z["met"], z["dtr"]), z["sweat"], z["valid"], w, h, c)
    tab = build_sweat_table(w, h, c)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, tdb=tab.axes[0], rh=tab.axes[1], met=tab.axes[2], dtr=tab.axes[3],
                        sweat=tab.sweat, valid=tab.valid)
    return tab


def mean_radiant_offset(shortwave_w_m2, outdoors) -> np.ndarray:
    """Mean radiant minus air temperature (degC): tr_offset_sun_c x SW/800 outdoors in sun, 0 indoors (§7.5)."""
    sw = np.asarray(shortwave_w_m2, dtype=float)
    return np.where(np.asarray(outdoors, dtype=bool), param("tr_offset_sun_c") * sw / 800.0, 0.0)


def indoor_temperature(outdoor_tdb: np.ndarray, roof: str = "concrete", cooling: str = "none") -> np.ndarray:
    """Indoor air temperature from an hourly outdoor series: offset by roof/cooling, lagged ``indoor_lag_h`` (§7.5)."""
    if cooling == "ac":
        offset = param("indoor_offset_ac_c")
    elif cooling == "cooler":
        offset = param("indoor_offset_cooler_c")
    else:
        offset = param({"concrete": "indoor_offset_concrete_c", "tin_asbestos": "indoor_offset_tin_roof_c",
                        "thatch": "indoor_offset_thatch_c"}[roof])
    lag = int(param("indoor_lag_h"))
    t = np.asarray(outdoor_tdb, dtype=float)
    lagged = np.concatenate([np.full(lag, t[0]), t[:-lag]]) if lag > 0 else t
    return lagged + offset


def met_for_occupation(occupation: str) -> float:
    return param({"home": "met_home", "office": "met_office", "vendor": "met_vendor", "delivery": "met_delivery",
                  "construction_farm": "met_construction_farm"}[occupation])


def wet_bulb_stull(tdb, rh) -> np.ndarray:
    """Wet-bulb temperature (degC), Stull 2011 empirical formula (valid RH 5-99 %, T -20..50 degC)."""
    t, r = np.asarray(tdb, dtype=float), np.asarray(rh, dtype=float)
    return (t * np.arctan(0.151977 * np.sqrt(r + 8.313659)) + np.arctan(t + r) - np.arctan(r - 1.676331)
            + 0.00391838 * r ** 1.5 * np.arctan(0.023101 * r) - 4.686035)


def heat_index_noaa(tdb, rh) -> np.ndarray:
    """NOAA heat index (degC): Rothfusz regression with the NWS adjustments; simple formula below 80 degF."""
    t = np.asarray(tdb, dtype=float) * 9 / 5 + 32
    r = np.asarray(rh, dtype=float)
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + r * 0.094)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r - 6.83783e-3 * t ** 2
          - 5.481717e-2 * r ** 2 + 1.22874e-3 * t ** 2 * r + 8.5282e-4 * t * r ** 2 - 1.99e-6 * t ** 2 * r ** 2)
    adj_dry = np.where((r < 13) & (t >= 80) & (t <= 112),
                       -((13 - r) / 4) * np.sqrt(np.clip((17 - np.abs(t - 95)) / 17, 0, None)), 0.0)
    adj_wet = np.where((r > 85) & (t >= 80) & (t <= 87), ((r - 85) / 10) * ((87 - t) / 5), 0.0)
    out_f = np.where((simple + t) / 2 < 80, simple, hi + adj_dry + adj_wet)
    return (out_f - 32) * 5 / 9
