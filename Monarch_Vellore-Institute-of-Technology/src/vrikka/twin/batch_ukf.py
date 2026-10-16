"""Batched personal twins: N patients' UKFs advanced together (master plan §10, §12.2; Part 4 feature builder).

Mathematically identical to :class:`vrikka.twin.ukf_twin.KidneyTwin` (same Merwe scaled sigma points, unscented
transform, measurement models, missing-channel rule, scalar lab update; tested to match it to 1e-8), but the state is
(N, 5), the covariance (N, 5, 5), and one physiology call advances all N x 11 sigma points (or N x n_draws Monte-Carlo
draws) at once. Inputs are hourly arrays of shape (T, N).

The 72-hour risk applies exactly the label rule: ``kdigo_daily_matrix`` on [last 7 daily estimates, today, 3 future
08:00 values] with each patient's §9.3 baseline, then ``aki_onsets`` in the future columns (Decisions v1 item 5).
"""
from __future__ import annotations

import math

import numpy as np

from vrikka.config import param
from vrikka.physiology.batch import exertion_update_vec, stack_params, step_hour_vec
from vrikka.physiology.equations import aki_onsets, kdigo_daily_matrix
from vrikka.physiology.renal import CHANNELS, INPUT_DEFAULTS, Params, exertion_target
from vrikka.twin import measurement

NX = 5
SAMPLE_IDX = (23, 47, 71)        # state after these hours (inputs start at 08:00) = 08:00 on days +1, +2, +3


def merwe_weights(n: int = NX) -> tuple[np.ndarray, np.ndarray, float]:
    alpha, beta, kappa = param("ukf_alpha"), param("ukf_beta"), param("ukf_kappa")
    lam = alpha ** 2 * (n + kappa) - n
    wm = np.full(2 * n + 1, 1.0 / (2 * (n + lam)))
    wc = wm.copy()
    wm[0] = lam / (n + lam)
    wc[0] = lam / (n + lam) + (1 - alpha ** 2 + beta)
    return wm, wc, lam


class BatchTwin:
    def __init__(self, params: list[Params], hr_base, sbp_base, beta_blocker, cr0, w_dry0=None):
        self.params = params
        self.N = len(params)
        self.P1 = stack_params(params)
        self.hr_base = np.asarray(hr_base, dtype=float)
        self.sbp_base = np.asarray(sbp_base, dtype=float)
        self.bb = np.asarray(beta_blocker, dtype=bool)
        cr0 = np.asarray(cr0, dtype=float)
        w_dry0 = self.P1["weight_kg"].copy() if w_dry0 is None else np.asarray(w_dry0, dtype=float)
        self.wm, self.wc, self.lam = merwe_weights()
        self.x = np.column_stack([np.zeros(self.N), np.zeros(self.N), cr0, np.zeros(self.N), w_dry0])
        p0 = np.zeros((self.N, NX, NX))
        p0[:, 0, 0] = param("ukf_p0_v_tot") ** 2
        p0[:, 1, 1] = param("ukf_p0_v_ecf") ** 2
        p0[:, 2, 2] = (param("ukf_p0_cr_frac") * cr0) ** 2
        p0[:, 3, 3] = param("ukf_p0_log_theta") ** 2
        p0[:, 4, 4] = param("ukf_p0_w_dry") ** 2
        self.P = p0
        self.Q = np.diag([param("ukf_q_v_tot") ** 2, param("ukf_q_v_ecf") ** 2, param("ukf_q_cr") ** 2,
                          param("ukf_q_log_theta") ** 2, param("ukf_q_w_dry") ** 2])
        sd = np.stack([measurement.noise_sd(bool(b)) for b in self.bb])            # (N, 3)
        self.R = np.zeros((self.N, 3, 3))
        self.R[:, np.arange(3), np.arange(3)] = sd ** 2
        self.hr_gain = np.where(self.bb, param("k_hr") * param("k_hr_beta_blocker_mult"), param("k_hr"))
        self.eff: dict[str, np.ndarray] | None = None
        self.cr_daily: list[np.ndarray] = [cr0.copy()]
        self.lag = {ch: np.exp(-math.log(2.0) / self.P1[f"half_life_{ch}"]) for ch in CHANNELS}
        self.ex_lag = np.exp(-1.0 / self.P1["tau_ex_h"])

    # ------------------------------------------------------------------ helpers
    def sigma_points(self, x: np.ndarray | None = None, P: np.ndarray | None = None) -> np.ndarray:
        x = self.x if x is None else x
        P = self.P if P is None else P
        L = np.linalg.cholesky((NX + self.lam) * P)                 # (N, 5, 5) lower; offsets = columns of L
        off = np.transpose(L, (0, 2, 1))                            # rows = columns of L (= filterpy's U rows)
        return np.concatenate([x[:, None, :], x[:, None, :] + off, x[:, None, :] - off], axis=1)   # (N, 11, 5)

    def _start_eff(self, day: dict) -> None:
        if self.eff is None:
            self.eff = {ch: np.broadcast_to(np.asarray(day.get(ch, 0.0), dtype=float), (24, self.N))[0].copy()
                        for ch in CHANNELS}
            self.eff["ex"] = np.zeros(self.N)

    def _run(self, states: np.ndarray, inputs: dict, record: tuple[str, ...], overrides: dict | None = None) -> dict:
        """states (N, K, 5); inputs map names to (T, N) hourly arrays, (N,) per-patient constants or scalars ->
        recorded arrays (T, N, K).

        Steps hour by hour itself (same step functions as ``simulate_vec``) so each hour's inputs are expanded to the
        N x K rows only for that hour: memory stays small with 50-200 draws per patient.
        """
        n, k, _ = states.shape
        P = {key: np.repeat(v, k) for key, v in self.P1.items()}
        for key, v in (overrides or {}).items():
            P[key] = np.repeat(np.broadcast_to(np.asarray(v, dtype=float), (n,)), k)
        P["theta_sweat"] = np.exp(states[:, :, 3]).ravel()
        arrs = {key: np.asarray(inputs.get(key, default), dtype=float) for key, default in INPUT_DEFAULTS.items()}
        T = max([a.shape[0] for a in arrs.values() if a.ndim == 2] or [1])
        const = {key: np.repeat(a, k) for key, a in arrs.items() if a.ndim == 1}     # per-patient constants (N,)

        def at(key, t):
            a = arrs[key]
            if a.ndim == 2:
                return np.repeat(a[t], k)
            return const[key] if a.ndim == 1 else float(a)

        v_tot = np.maximum(states[:, :, 0], 0.0).ravel()
        v_ecf = np.clip(states[:, :, 1].ravel(), 0.0, v_tot)
        cr = np.maximum(states[:, :, 2], 0.2).ravel()
        eff = {ch: np.repeat(self.eff[ch], k) for ch in CHANNELS}
        ex = np.repeat(self.eff["ex"], k)
        lag = {ch: np.exp(-math.log(2.0) / P[f"half_life_{ch}"]) for ch in CHANNELS}
        out = {key: np.empty((T, n * k)) for key in record}
        for t in range(T):
            for ch in CHANNELS:
                eff[ch] = eff[ch] * lag[ch] + (1 - lag[ch]) * at(ch, t)
            ex = exertion_update_vec(ex, at("met", t), P)
            v_tot, v_ecf, cr, gfr = step_hour_vec(P, v_tot, v_ecf, cr, eff, at("sweat_l_h", t), at("gi_loss_l_h", t),
                                                  at("intake_l_h", t), at("fever_excess_c", t), at("phi_mult", t),
                                                  at("ors_l_h", t), ex)
            cur = {"v_tot": v_tot, "v_ecf": v_ecf, "cr": cr, "gfr": gfr}
            for key in record:
                out[key][t] = cur[key]
        return {key: v.reshape(T, n, k) for key, v in out.items()}

    @staticmethod
    def _ut(points: np.ndarray, wm: np.ndarray, wc: np.ndarray, noise) -> tuple[np.ndarray, np.ndarray]:
        mean = np.einsum("k,nkd->nd", wm, points)
        dev = points - mean[:, None, :]
        cov = np.einsum("k,nki,nkj->nij", wc, dev, dev) + noise
        return mean, cov

    # ------------------------------------------------------------------ filter steps
    def predict(self, day: dict) -> None:
        """Advance 24 h (08:00 -> 08:00). ``day`` maps INPUT_DEFAULTS names to (24, N) arrays or scalars."""
        self._start_eff(day)
        sig = self.sigma_points()
        out = self._run(sig, day, record=("v_tot", "v_ecf", "cr"))
        prop = sig.copy()
        prop[:, :, 0], prop[:, :, 1], prop[:, :, 2] = out["v_tot"][-1], out["v_ecf"][-1], out["cr"][-1]
        self.x, P = self._ut(prop, self.wm, self.wc, self.Q)
        self.P = 0.5 * (P + np.transpose(P, (0, 2, 1)))
        for ch in CHANNELS:
            tgt = np.broadcast_to(np.asarray(day.get(ch, 0.0), dtype=float), (24, self.N))
            for h in range(24):
                self.eff[ch] = self.eff[ch] * self.lag[ch] + (1 - self.lag[ch]) * tgt[h]
        met = np.broadcast_to(np.asarray(day.get("met", 0.0), dtype=float), (24, self.N))
        for h in range(24):
            tgt = exertion_target(met[h], self.P1["ex_met_threshold"], self.P1["ex_met_span"])
            self.eff["ex"] = self.eff["ex"] * self.ex_lag + (1 - self.ex_lag) * tgt
        self.cr_daily.append(self.x[:, 2].copy())

    def hx(self, pts: np.ndarray, fever_excess: np.ndarray) -> np.ndarray:
        """Expected [weight, resting HR, SBP] for points (N, K, 5)."""
        w = pts[:, :, 4] - pts[:, :, 0]
        hr = (self.hr_base[:, None] + self.hr_gain[:, None] * pts[:, :, 1]
              + param("hr_fever_bpm_per_c") * np.maximum(fever_excess, 0.0)[:, None])
        sbp = self.sbp_base[:, None] - param("k_bp") * pts[:, :, 1]
        return np.stack([w, hr, sbp], axis=-1)

    def update(self, z: np.ndarray, fever_excess: np.ndarray) -> None:
        """Morning measurements z (N, 3) = [weight, resting HR, SBP], NaN = missing (R inflated for that channel)."""
        z = np.asarray(z, dtype=float)
        missing = ~np.isfinite(z)
        act = ~missing.all(axis=1)
        if not act.any():
            return
        R = self.R.copy()
        mi, mj = np.nonzero(missing)
        R[mi, mj, mj] = param("missing_channel_r")
        sig = self.sigma_points()
        Z = self.hx(sig, np.asarray(fever_excess, dtype=float))
        zp, S = self._ut(Z, self.wm, self.wc, R)
        zf = np.where(missing, zp, z)
        dx = sig - self.x[:, None, :]
        dz = Z - zp[:, None, :]
        Pxz = np.einsum("k,nki,nkj->nij", self.wc, dx, dz)
        K = Pxz @ np.linalg.inv(S)
        x_new = self.x + np.einsum("nij,nj->ni", K, zf - zp)
        P_new = self.P - K @ S @ np.transpose(K, (0, 2, 1))
        P_new = 0.5 * (P_new + np.transpose(P_new, (0, 2, 1)))
        self.x = np.where(act[:, None], x_new, self.x)
        self.P = np.where(act[:, None, None], P_new, self.P)
        self.cr_daily[-1] = self.x[:, 2].copy()

    def update_lab(self, cr_lab: np.ndarray) -> None:
        """Lab creatinine (mg/dL) at 08:00 for some patients (NaN = no lab): scalar Kalman update of the cr state."""
        lab = np.asarray(cr_lab, dtype=float)
        m = np.isfinite(lab)
        if not m.any():
            return
        Pm, xm, lv = self.P[m], self.x[m], lab[m]
        S = Pm[:, 2, 2] + (param("cr_lab_cv") * lv) ** 2
        K = Pm[:, :, 2] / S[:, None]
        self.x[m] = xm + K * (lv - xm[:, 2])[:, None]
        self.P[m] = Pm - K[:, :, None] * Pm[:, 2, None, :]
        self.cr_daily[-1] = self.x[:, 2].copy()

    @property
    def theta(self) -> np.ndarray:
        return np.exp(self.x[:, 3])

    def gfr_frac_now(self) -> np.ndarray:
        """Modelled filtration (fraction of personal baseline) at the posterior mean with the current drug and exertion
        effects (same formula as the engine)."""
        P = self.P1
        d = np.maximum(self.x[:, 1], 0.0) / (P["ecv_frac"] * P["weight_kg"])
        h = np.where(d > 0, d ** P["hill_n"] / (d ** P["hill_n"] + P["d50"] ** P["hill_n"]), 0.0)
        e = self.eff["nsaid"] if self.eff else np.zeros(self.N)
        ras = self.eff["ras"] if self.eff else np.zeros(self.N)
        ex = self.eff["ex"] if self.eff else np.zeros(self.N)
        i_pg = np.where(e > 0, e / (e + P["nsaid_e50"]), 0.0)
        prot = P["a_tot"] * (P["aff_share"] * (1 - i_pg) + (1 - P["aff_share"]) * (1 - P["i_ras"] * ras))
        return (1 - h * (1 - prot)) * (1 - P["k_ex"] * ex)

    # ------------------------------------------------------------------ risk
    def risk_72h(self, future: dict, baseline: np.ndarray, n_draws: int, rng: np.random.Generator) -> dict:
        """Monte-Carlo P(KDIGO onset within 72 h) per patient, plus the predicted creatinine peak and GFR minimum."""
        P = 0.5 * (self.P + np.transpose(self.P, (0, 2, 1))) + 1e-9 * np.eye(NX)
        L = np.linalg.cholesky(P)
        draws = self.x[:, None, :] + np.einsum("nij,nkj->nki", L, rng.standard_normal((self.N, n_draws, NX)))
        out = self._run(draws, future, record=("cr", "gfr"))
        fut = np.transpose(out["cr"][list(SAMPLE_IDX)], (1, 2, 0))                 # (N, n, 3)
        hist = np.stack(self.cr_daily[-8:-1], axis=1) if len(self.cr_daily) > 1 else np.zeros((self.N, 0))
        today = np.maximum(draws[:, :, 2], 0.2)[:, :, None]
        series = np.concatenate([np.broadcast_to(hist[:, None, :], (self.N, n_draws, hist.shape[1])), today, fut],
                                axis=2).reshape(self.N * n_draws, -1)
        stages = kdigo_daily_matrix(series, np.repeat(np.asarray(baseline, dtype=float), n_draws))
        hit = aki_onsets(stages)[:, -3:].any(axis=1).reshape(self.N, n_draws)
        base = np.asarray(baseline, dtype=float)
        return {
            "risk": hit.mean(axis=1),
            "cr_peak_ratio": (out["cr"].max(axis=0) / base[:, None]).mean(axis=1),
            "gfr_min_frac": (out["gfr"].min(axis=0) / self.P1["gfr_base"][:, None]).mean(axis=1),
        }
