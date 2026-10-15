"""Personal kidney twin: Unscented Kalman Filter over hidden body-water and kidney states (master plan §10).

State x = [v_tot (L), v_ecf (L), cr (mg/dL), log theta_sweat, w_dry (kg)].
- Daily cycle 08:00 -> 08:00: ``predict`` runs the physiology engine hour by hour for all 11 sigma points at once
  (vectorised), with that day's exposures (sweat from weather + routine, reported symptoms, tablets, ORS).
- ``update`` uses the morning weight / resting HR / home SBP; a missing channel gets R = missing_channel_r
  (registry) for that step, so dimensions never change.
- ``update_lab`` is a scalar Kalman update of creatinine (CV ``cr_lab_cv``).
- ``cr_daily`` keeps the 08:00 creatinine estimate per day; the Monte-Carlo risk reads it through the same
  daily KDIGO functions as the labels (Decisions v1 item 5).

theta_sweat multiplies (1 - phi_drink), so learning theta from daily weight means the twin learns each person's NET
unreplaced fluid loss; population uncertainty in phi_drink is absorbed by personalisation (Decisions v2 A-5b).
All noise settings come from the registry. filterpy (MIT) provides sigma points and the unscented transform.
"""

from __future__ import annotations

import copy

import numpy as np
from filterpy.kalman import MerweScaledSigmaPoints, unscented_transform

from vrikka.config import param
from vrikka.physiology.batch import simulate_vec, stack_params
from vrikka.physiology.renal import CHANNELS as DRUGS
from vrikka.physiology.renal import INPUT_DEFAULTS, Params, drug_effect
from vrikka.twin import measurement


class KidneyTwin:
    def __init__(
        self,
        p: Params,
        hr_base: float,
        sbp_base: float,
        beta_blocker: bool = False,
        cr0: float | None = None,
        w_dry0: float | None = None,
    ):
        self.p = p
        self.hr_base, self.sbp_base, self.beta_blocker = hr_base, sbp_base, beta_blocker
        self.points = MerweScaledSigmaPoints(
            n=5, alpha=param("ukf_alpha"), beta=param("ukf_beta"), kappa=param("ukf_kappa")
        )
        cr0 = p.cr_base if cr0 is None else cr0
        self.x = np.array([0.0, 0.0, cr0, 0.0, p.weight_kg if w_dry0 is None else w_dry0])
        self.P = np.diag(
            [
                param("ukf_p0_v_tot") ** 2,
                param("ukf_p0_v_ecf") ** 2,
                (param("ukf_p0_cr_frac") * cr0) ** 2,
                param("ukf_p0_log_theta") ** 2,
                param("ukf_p0_w_dry") ** 2,
            ]
        )
        self.Q = np.diag(
            [
                param("ukf_q_v_tot") ** 2,
                param("ukf_q_v_ecf") ** 2,
                param("ukf_q_cr") ** 2,
                param("ukf_q_log_theta") ** 2,
                param("ukf_q_w_dry") ** 2,
            ]
        )
        self.R = np.diag(measurement.noise_sd(beta_blocker) ** 2)
        self.eff: dict[str, float] | None = None
        self.cr_daily: list[float] = [float(cr0)]  # 08:00 creatinine estimates, one per day
        self._P1 = stack_params([p])

    # ------------------------------------------------------------------ helpers
    def _engine_params(self, log_theta: np.ndarray, overrides: dict | None = None) -> dict:
        n = log_theta.shape[0]
        P = {k: np.repeat(v, n) for k, v in self._P1.items()}
        for k, v in (overrides or {}).items():
            P[k] = np.broadcast_to(np.asarray(v, dtype=float), (n,)).copy()
        P["theta_sweat"] = np.exp(log_theta)
        return P

    def _start_eff(self, day: dict) -> dict:
        if self.eff is None:
            self.eff = {ch: float(np.asarray(day.get(ch, 0.0)).ravel()[0]) for ch in DRUGS}
        return self.eff

    def _run(
        self,
        states: np.ndarray,
        inputs: dict,
        overrides: dict | None = None,
        record: tuple[str, ...] = ("v_tot", "v_ecf", "cr"),
    ) -> dict:
        n = states.shape[0]
        s0 = {
            "v_tot": np.maximum(states[:, 0], 0.0),
            "v_ecf": np.clip(states[:, 1], 0.0, np.maximum(states[:, 0], 0.0)),
            "cr": np.maximum(states[:, 2], 0.2),
        }
        eff0 = {ch: np.full(n, self.eff[ch]) for ch in DRUGS}
        return simulate_vec(self._engine_params(states[:, 3], overrides), inputs, s0, eff0, record=record)

    # ------------------------------------------------------------------ filter steps
    def predict(self, day: dict) -> None:
        """Advance 24 h (08:00 -> 08:00). ``day`` maps INPUT_DEFAULTS names to 24-hour arrays (or scalars)."""
        self._start_eff(day)
        inputs = {k: np.broadcast_to(np.asarray(day.get(k, v), dtype=float), (24,)) for k, v in INPUT_DEFAULTS.items()}
        sig = self.points.sigma_points(self.x, self.P)
        out = self._run(sig, inputs)
        prop = sig.copy()
        prop[:, 0], prop[:, 1], prop[:, 2] = out["v_tot"][-1], out["v_ecf"][-1], out["cr"][-1]
        self.x, self.P = unscented_transform(prop, self.points.Wm, self.points.Wc, self.Q)
        self.P = 0.5 * (self.P + self.P.T)
        for ch in DRUGS:
            for h in range(24):
                self.eff[ch] = drug_effect(self.eff[ch], float(inputs[ch][h]), self.p.half_life_h[ch])
        self.cr_daily.append(float(self.x[2]))

    def update(
        self,
        weight: float | None = None,
        hr: float | None = None,
        sbp: float | None = None,
        fever_excess_c: float = 0.0,
    ) -> None:
        """Morning measurements; None/NaN = missing (R inflated for that channel)."""
        z = np.array([weight, hr, sbp], dtype=float)
        missing = ~np.isfinite(z)
        if missing.all():
            return
        R = self.R.copy()
        R[missing, missing] = param("missing_channel_r")
        sig = self.points.sigma_points(self.x, self.P)
        Z = measurement.hx(sig, self.hr_base, self.sbp_base, self.beta_blocker, fever_excess_c)
        zp, S = unscented_transform(Z, self.points.Wm, self.points.Wc, R)
        z = np.where(missing, zp, z)
        Pxz = sum(self.points.Wc[i] * np.outer(sig[i] - self.x, Z[i] - zp) for i in range(sig.shape[0]))
        K = Pxz @ np.linalg.inv(S)
        self.x = self.x + K @ (z - zp)
        self.P = self.P - K @ S @ K.T
        self.P = 0.5 * (self.P + self.P.T)
        self.cr_daily[-1] = float(self.x[2])

    def update_lab(self, cr_lab: float) -> None:
        """Lab creatinine (mg/dL) taken at 08:00: scalar Kalman update on the creatinine state."""
        H = np.zeros((1, 5))
        H[0, 2] = 1.0
        R = np.array([[(param("cr_lab_cv") * cr_lab) ** 2]])
        K = self.P @ H.T @ np.linalg.inv(H @ self.P @ H.T + R)
        self.x = self.x + (K @ (np.array([cr_lab]) - H @ self.x)).ravel()
        self.P = (np.eye(5) - K @ H) @ self.P
        self.cr_daily[-1] = float(self.x[2])

    @property
    def theta(self) -> float:
        return float(np.exp(self.x[3]))

    def snapshot(self) -> KidneyTwin:
        return copy.deepcopy(self)
