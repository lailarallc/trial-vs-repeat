"""Demo golden lock — Trial vs Repeat.

Locks the demo repeat headline the deployed app shows, computed straight from the
tested engine (``app.trial_repeat.repeat_summary``) on the seeded demo panel:
trier/mature/immature counts, repeaters, rate, and the maturity cutoff.

**Credential-free by design.** A golden pins DEMO output, so it must not import
the client-mode scaffolding (``lailara_engagement``). That keeps this gate green
regardless of the CI PAT — a token expiry can degrade client-mode coverage but can
never turn the demo invariant red. The client-mode fidelity lock (that
``compute_trial_repeat`` reproduces these exact engine numbers) and the direct
right-censoring boundary fixture live in ``tests/test_client_mode.py``.
"""
from __future__ import annotations


def test_demo_repeat_summary_locked():
    from app.trial_repeat import repeat_summary  # app engine — no lailara_engagement

    eng = repeat_summary(window_weeks=12)
    assert eng["n_triers"] == 4487
    assert eng["n_mature"] == 4456
    assert eng["n_immature"] == 31
    assert eng["n_repeaters"] == 2188
    assert round(eng["repeat_rate"], 4) == 0.491
    assert str(eng["maturity_cutoff_date"])[:10] == "2025-10-06"
