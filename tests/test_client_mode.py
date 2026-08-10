"""Client-mode tests for Trial vs Repeat (checklist §6).

Skipped unless the shared ``lailara_engagement`` lib is installed. Fixtures
generated on the fly — no client identifiers, no committed data.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lailara_engagement")

import client_mode  # noqa: E402  (repo root on path via cwd)

# as_of 2026-01-31, window 12w -> cutoff 2025-11-08. H4 immature; H5 repeat out of window.
LEDGER = (
    "household_id,purchase_date,product_line\n"
    "H1,2025-06-01,Sauces\nH1,2025-07-01,Sauces\n"
    "H2,2025-06-15,Sauces\n"
    "H3,2025-08-01,Snacks\nH3,2025-09-01,Snacks\n"
    "H4,2026-01-15,Sauces\n"
    "H5,2025-07-01,Snacks\nH5,2025-12-01,Snacks\n"
)


def _write(d: Path, text=LEDGER, name="transactions.csv"):
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


def _cfg(d: Path, *, window=12, columns=None):
    import yaml
    p = d / "engagement.demo.yml"
    p.write_text(yaml.safe_dump({
        "client": {"name": "Cinderhaven Provisions (demo)"}, "engagement": {"id": "T-1"},
        "as_of_date": "2026-01-31", "demo": True,
        "basis": {"repeat_window_weeks": window}, "columns": columns or {}}), encoding="utf-8")
    return p


def test_clean_run_computes_repeat_with_maturity_cutoff(tmp_path):
    inp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path)), str(inp), str(tmp_path / "out"))
    assert res["status"] == "ok"
    assert res["n_triers"] == 5
    assert res["n_mature"] == 4
    assert res["n_immature"] == 1        # H4 excluded, not a non-repeater
    assert res["n_repeaters"] == 2
    assert res["repeat_rate"] == 0.5
    assert Path(res["report"]).is_file()


def test_deliverable_states_right_censoring_and_draft(tmp_path):
    inp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path)), str(inp), str(tmp_path / "out"))
    html = Path(res["report"]).read_text(encoding="utf-8")
    assert "50.0% repeat within 12 weeks" in html
    assert "2025-11-08" in html                     # maturity cutoff stated
    assert "excluded from the rate" in html
    assert "household panel (not store POS)" in html   # provenance grain note
    assert "DRAFT" in html


def test_repeat_window_and_cutoff_track_config_not_hardcoded(tmp_path):
    """The rendered repeat window ('within N weeks', 'N-week window') and the
    maturity cutoff date must come from basis.repeat_window_weeks, not a
    hardcoded 12. The deliverable test asserts only the demo's own 'within 12
    weeks' / '2025-11-08' — a positive-only check a hardcoded 12 would also
    pass, the gap that let trade-spend quote 26 weeks as 'trailing 52 weeks'.

    Both halves: feed a distinctive window and assert the label + cutoff track
    it (cutoff = as_of − 8w = 2025-12-06), AND assert the demo default is absent."""
    inp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path, window=8)), str(inp), str(tmp_path / "out"))
    assert res["status"] == "ok"
    html = Path(res["report"]).read_text(encoding="utf-8")
    assert "within 8 weeks" in html and "8-week window" in html
    assert "2025-12-06" in html                       # cutoff tracks the 8-week window
    assert "within 12 weeks" not in html              # demo default must not survive
    assert "12-week window" not in html and "2025-11-08" not in html


def test_missing_purchase_date_blocks(tmp_path):
    import pandas as pd
    inp = tmp_path / "transactions.csv"
    pd.read_csv(_write(tmp_path, name="tmp.csv")).drop(columns=["purchase_date"]).to_csv(inp, index=False)
    res = client_mode.run(str(_cfg(tmp_path)), str(inp), str(tmp_path / "out"))
    assert res["status"] == "blocked"
    assert "purchase_date" in Path(res["readiness_report"]).read_text(encoding="utf-8")


def test_missing_window_declaration_errors(tmp_path):
    import yaml
    inp = _write(tmp_path)
    cfg = tmp_path / "engagement.demo.yml"
    cfg.write_text(yaml.safe_dump({
        "client": {"name": "x"}, "engagement": {"id": "y"}, "as_of_date": "2026-01-31",
        "demo": True, "columns": {}}), encoding="utf-8")   # no basis.repeat_window_weeks
    with pytest.raises(Exception):
        client_mode.run(str(cfg), str(inp), str(tmp_path / "out"))


def test_per_product_line_breakdown(tmp_path):
    inp = _write(tmp_path)
    res = client_mode.run(str(_cfg(tmp_path)), str(inp), str(tmp_path / "out"))
    html = Path(res["report"]).read_text(encoding="utf-8")
    assert "By product line" in html
    assert "Sauces" in html and "Snacks" in html


def test_header_mapping(tmp_path):
    text = "Panelist,Purchase Date\nH1,2025-06-01\nH1,2025-07-01\nH2,2025-06-15\n"
    inp = _write(tmp_path, text=text)
    cfg = _cfg(tmp_path, columns={"household_id": "Panelist", "purchase_date": "Purchase Date"})
    res = client_mode.run(str(cfg), str(inp), str(tmp_path / "out"))
    assert res["status"] == "ok"
    assert res["n_triers"] == 2


# --- Engine-fidelity lock (moved here from the demo golden, 2026-08-05) ------------
# These pin that the client-mode compute reproduces the tested engine — inherently
# lib-dependent, so they belong in the client-mode suite, not the credential-free
# demo golden.

def test_client_compute_matches_engine_on_demo_panel():
    """client-mode compute_trial_repeat reproduces the engine's demo repeat numbers."""
    from app.trial_repeat import AS_OF, repeat_summary
    import cinderhaven_household_panel as panel
    from client_mode import compute_trial_repeat

    eng = repeat_summary(window_weeks=12)
    tx = panel.get_transactions().rename(columns={"date": "purchase_date"})
    mine = compute_trial_repeat(tx, 12, AS_OF)
    assert mine["n_mature"] == eng["n_mature"] == 4456
    assert mine["n_repeaters"] == eng["n_repeaters"] == 2188
    assert round(mine["repeat_rate"], 4) == round(eng["repeat_rate"], 4) == 0.491


def test_maturity_boundary_fixture():
    # as_of 2026-01-31, window 12w (84 days) -> maturity cutoff 2025-11-08.
    import pandas as pd
    from client_mode import compute_trial_repeat

    as_of = pd.Timestamp("2026-01-31")
    tx = pd.DataFrame([
        ("H1", "2025-06-01"), ("H1", "2025-07-01"),   # repeat in window -> repeater
        ("H2", "2025-06-15"),                          # no repeat -> non-repeater
        ("H3", "2025-08-01"), ("H3", "2025-09-01"),   # repeat in window -> repeater
        ("H4", "2026-01-15"),                          # immature (first purchase after cutoff)
        ("H5", "2025-07-01"), ("H5", "2025-12-01"),   # repeat OUTSIDE the 84-day window -> non-repeater
    ], columns=["household_id", "purchase_date"])
    tx["purchase_date"] = pd.to_datetime(tx["purchase_date"])
    r = compute_trial_repeat(tx, 12, as_of)
    assert r["n_triers"] == 5
    assert r["n_mature"] == 4          # H1,H2,H3,H5 mature; H4 immature
    assert r["n_immature"] == 1
    assert r["n_repeaters"] == 2       # H1,H3 (H5's repeat is out of window)
    assert r["repeat_rate"] == 0.5
    assert r["maturity_cutoff_date"] == "2025-11-08"
