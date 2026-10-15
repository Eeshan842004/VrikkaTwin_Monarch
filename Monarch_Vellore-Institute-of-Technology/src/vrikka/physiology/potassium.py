"""Stretch goal (COULD): first-order potassium model (master plan §9.6). Stub only in this build.

Planned form: K_target = K_base + b_gfr (1 - GFR/GFR_base) + b_ras onRAS + b_mra onMRA + b_nsaid I_PG
+ b_diet (dietK - usual) - b_thz onThiazide - b_loop onLoop; dK/dt = (K_target - K) / tau_K, with all b_* and tau_K in
the registry (``k_beta_*``, ``k_tau_h``). Endpoint K >= 6.0 within 72 h. Not built: it is not part of the fast or slow
clock, and lab potassium is handled by the guardrails (K >= 6.0 always triggers a same-day repeat + clinician alert).
"""


def potassium_step(*_args, **_kwargs):
    raise NotImplementedError("Potassium model is a stretch goal and is not built (master plan §9.6).")
