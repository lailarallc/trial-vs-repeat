"""Trial and repeat math — the analysis tool #4 adds on top of the shared panel.

Everything here is a pure read-side computation over ``get_transactions()``. Nothing
is seeded or hardcoded: trial is the first-ever purchase, repeat is a later purchase
within a window, and every summary number applies a maturity cutoff so recent triers
who have not yet had a full window to repeat are excluded (right-censoring — the
credibility make-or-break). The repeat window is a parameter throughout.

Grain notes:
- The panel spans burn-in (2023) + analysis (2024-2025); first-ever purchases are
  identified against the FULL history, which is why the burn-in runway matters.
- The two launch items (CHP-SB-010 leaky, CHP-PS-010 sticky) both launch in 2023-Q2,
  so their triers are always mature — the demo is stable at any window.
"""

import pandas as pd

import cinderhaven_household_panel as panel

AS_OF = pd.Timestamp(panel.DEMO_AS_OF_DATE)
N_HOUSEHOLDS = panel.N_HOUSEHOLDS


# ── Filtering ─────────────────────────────────────────────────────────
def _tx(product_line: str | None = None, retailer_id: str | None = None,
        sku: str | None = None) -> pd.DataFrame:
    """The transaction slice for a filter combination (brand-level unless sku given)."""
    tx = panel.get_transactions()
    if sku is not None:
        tx = tx[tx["sku_id"] == sku]
    if product_line is not None:
        tx = tx[tx["product_line"] == product_line]
    if retailer_id is not None:
        tx = tx[tx["retailer_id"] == retailer_id]
    return tx


def _first_purchase(tx: pd.DataFrame) -> pd.DataFrame:
    """Each household's first-ever purchase in this slice: the trial event.

    Columns: household_id, first_date, first_qi, first_ql. One row per household that
    ever bought in the slice.
    """
    fp = (
        tx.sort_values("date", kind="stable")
        .drop_duplicates("household_id", keep="first")
        .loc[:, ["household_id", "date", "quarter_index", "quarter_label"]]
        .rename(columns={"date": "first_date", "quarter_index": "first_qi",
                         "quarter_label": "first_ql"})
        .reset_index(drop=True)
    )
    return fp


def _window(weeks: int) -> pd.Timedelta:
    return pd.Timedelta(weeks=weeks)


def _mature_triers(fp: pd.DataFrame, win: pd.Timedelta) -> pd.DataFrame:
    """The triers whose full repeat window has elapsed before the as-of date.

    The single definition of maturity (right-censoring cutoff), so repeat_summary and
    depth_of_repeat can never disagree on who is mature.
    """
    return fp[fp["first_date"] + win <= AS_OF]


# ── Trial ─────────────────────────────────────────────────────────────
def trial_curve(product_line: str | None = None, retailer_id: str | None = None,
                sku: str | None = None) -> pd.DataFrame:
    """Cumulative first-ever-buyer curve, by quarter (calendar order, all 12 quarters).

    Columns: quarter_index, quarter_label, is_analysis, new_triers, cumulative_triers,
    cumulative_trial_rate (cumulative triers / all panel households).
    """
    from cinderhaven_household_panel import get_quarters

    tx = _tx(product_line, retailer_id, sku)
    fp = _first_purchase(tx)
    quarters = get_quarters()[["quarter_index", "label", "is_analysis"]].sort_values("quarter_index")

    new_by_q = fp.groupby("first_qi").size()
    rows = []
    cumulative = 0
    for qi, label, is_analysis in quarters.itertuples(index=False):
        new_triers = int(new_by_q.get(qi, 0))
        cumulative += new_triers
        rows.append({
            "quarter_index": qi,
            "quarter_label": label,
            "is_analysis": bool(is_analysis),
            "new_triers": new_triers,
            "cumulative_triers": cumulative,
            "cumulative_trial_rate": cumulative / N_HOUSEHOLDS,
        })
    return pd.DataFrame(rows)


# ── Repeat (with maturity cutoff) ─────────────────────────────────────
def repeat_summary(window_weeks: int, product_line: str | None = None,
                   retailer_id: str | None = None, sku: str | None = None) -> dict:
    """Repeat rate within ``window_weeks`` of first purchase, maturity-cutoff applied.

    A trier is *mature* if a full window has elapsed between their first purchase and
    the panel's as-of date; only mature triers count toward the repeat rate (recent
    triers who could not yet have repeated are excluded, not counted as non-repeaters).
    A trier *repeats* if they made any further purchase in the slice strictly after
    their first purchase and within the window.

    Returns: n_triers, n_mature, n_immature, n_repeaters, repeat_rate,
    maturity_cutoff_date (triers whose first purchase is after this are immature),
    window_weeks.
    """
    tx = _tx(product_line, retailer_id, sku)
    fp = _first_purchase(tx)
    win = _window(window_weeks)

    mature = _mature_triers(fp, win)
    n_immature = len(fp) - len(mature)

    if len(mature):
        joined = tx.merge(mature[["household_id", "first_date"]], on="household_id")
        in_window = (joined["date"] > joined["first_date"]) & (
            joined["date"] <= joined["first_date"] + win
        )
        joined = joined.assign(is_repeat=in_window)
        repeated = joined.groupby("household_id")["is_repeat"].any()
        n_repeaters = int(repeated.sum())
        repeat_rate = n_repeaters / len(mature)
    else:
        n_repeaters = 0
        repeat_rate = 0.0

    return {
        "n_triers": len(fp),
        "n_mature": len(mature),
        "n_immature": n_immature,
        "n_repeaters": n_repeaters,
        "repeat_rate": repeat_rate,
        "maturity_cutoff_date": (AS_OF - win),
        "window_weeks": window_weeks,
    }


# ── Failed-trial trade burn (the dollar behind the verdict) ──────────
# Owner-blessed assumption (2026-07-30): trial volume moves on promotion, and
# Cinderhaven promotions run ~18% average depth off retail (measured from the
# platform's promotions data; on the brand's ~$8.07 average unit that is ~$1.45
# of trade support per trial unit). The burn applies that depth to the actual
# first-purchase spend of mature triers who never repeated: trade dollars that
# bought sampling, not adoption. Panel-measured — never projected to a household
# universe (canonical: households carry no proxies).
# Copy-only context (never computed from): industry trade spend runs 15-25% of
# gross revenue, and ~72% of US trade promotions fail to break even.
TRIAL_PROMO_DEPTH = 0.18


def failed_trial_burn(window_weeks: int, product_line: str | None = None,
                      retailer_id: str | None = None, sku: str | None = None) -> dict:
    """Trade dollars burned on triers who never came back, for one filter slice.

    Basis: ``TRIAL_PROMO_DEPTH`` (assumed 18% promo depth) x the first-purchase
    spend of mature triers with no repeat within ``window_weeks``. Period: the
    panel history through the as-of date, maturity cutoff applied (same rule as
    ``repeat_summary``). Returns n_failed, failed_trial_spend, burn — all
    in-panel dollars (5,000-household panel), never universe-projected.
    """
    tx = _tx(product_line, retailer_id, sku)
    fp = (
        tx.sort_values("date", kind="stable")
        .drop_duplicates("household_id", keep="first")
        .loc[:, ["household_id", "date", "spend"]]
        .rename(columns={"date": "first_date", "spend": "first_spend"})
        .reset_index(drop=True)
    )
    win = _window(window_weeks)
    mature = fp[fp["first_date"] + win <= AS_OF]
    if not len(mature):
        return {"n_failed": 0, "failed_trial_spend": 0.0, "burn": 0.0}
    joined = tx.merge(mature[["household_id", "first_date"]], on="household_id")
    in_window = (joined["date"] > joined["first_date"]) & (
        joined["date"] <= joined["first_date"] + win
    )
    repeated = joined.assign(is_repeat=in_window).groupby("household_id")["is_repeat"].any()
    failed = mature[mature["household_id"].isin(repeated[~repeated].index)]
    spend = float(failed["first_spend"].sum())
    return {
        "n_failed": int(len(failed)),
        "failed_trial_spend": spend,
        "burn": spend * TRIAL_PROMO_DEPTH,
    }


# ── Cohort retention triangle ─────────────────────────────────────────
def cohort_retention(product_line: str | None = None, retailer_id: str | None = None,
                     sku: str | None = None) -> pd.DataFrame:
    """Retention triangle: cohort by first-purchase quarter × later-quarter retention.

    For cohort c (households whose first purchase was quarter c) and quarter q >= c,
    retention = share of the cohort who purchased again in quarter q. Offset 0 is
    always 1.0 (the trial quarter). Recent cohorts have fewer observable offsets — the
    triangle shape IS the right-censoring, shown rather than hidden.

    Columns: cohort_qi, cohort_label, cohort_size, quarter_index, offset, retention.
    """
    from cinderhaven_household_panel import get_quarters

    tx = _tx(product_line, retailer_id, sku)
    fp = _first_purchase(tx)
    labels = dict(zip(get_quarters()["quarter_index"], get_quarters()["label"]))
    max_qi = int(tx["quarter_index"].max()) if len(tx) else 0

    buyers_by_q = {qi: set(g["household_id"].unique()) for qi, g in tx.groupby("quarter_index")}

    rows = []
    for cohort_qi, group in fp.groupby("first_qi"):
        members = set(group["household_id"])
        size = len(members)
        for q in range(cohort_qi, max_qi + 1):
            retained = len(members & buyers_by_q.get(q, set()))
            rows.append({
                "cohort_qi": cohort_qi,
                "cohort_label": labels[cohort_qi],
                "cohort_size": size,
                "quarter_index": q,
                "offset": q - cohort_qi,
                "retention": retained / size,
            })
    return pd.DataFrame(rows)


# ── Depth of repeat ───────────────────────────────────────────────────
def depth_of_repeat(window_weeks: int, product_line: str | None = None,
                    retailer_id: str | None = None, sku: str | None = None) -> dict:
    """Distribution of purchase depth among mature triers, within the window.

    Depth = number of distinct purchase days in [first_purchase, first_purchase +
    window]. 1x = trial only (never came back), 2x = came back once, 3x+ = twice or
    more. Returns counts and shares per bucket plus n_mature.
    """
    tx = _tx(product_line, retailer_id, sku)
    fp = _first_purchase(tx)
    win = _window(window_weeks)
    mature = _mature_triers(fp, win)

    buckets = {"1x": 0, "2x": 0, "3x+": 0}
    if len(mature):
        joined = tx.merge(mature[["household_id", "first_date"]], on="household_id")
        joined = joined[
            (joined["date"] >= joined["first_date"])
            & (joined["date"] <= joined["first_date"] + win)
        ]
        trips = joined.groupby("household_id")["date"].nunique()
        # Triers with no in-window row at all (shouldn't happen — the trial is in
        # window) default to 1x via reindex.
        trips = trips.reindex(mature["household_id"], fill_value=1)
        buckets["1x"] = int((trips == 1).sum())
        buckets["2x"] = int((trips == 2).sum())
        buckets["3x+"] = int((trips >= 3).sum())

    n = len(mature)
    shares = {k: (v / n if n else 0.0) for k, v in buckets.items()}
    return {"counts": buckets, "shares": shares, "n_mature": n}


# ── Buyer flow (leaky bucket), scope-aware ────────────────────────────
def buyer_flow(product_line: str | None = None, retailer_id: str | None = None,
               sku: str | None = None) -> pd.DataFrame:
    """New / retained / lapsed buyer flow per adjacent quarter pair, for any scope.

    Counts are PANEL-MEASURED households, not projected to brand scale. This used to
    say it mirrors the panel's ``get_buyer_flow``; that stopped being true at panel
    0.2.0, which multiplies its absolute counts by the panel's locked projection
    factor k while this function keeps the raw household counts. (The specific value
    of k is not cited here — it lives in the panel package and would only go stale in
    a copy.) Both scales are internally consistent -- this tool reports no absolute
    dollar figure anywhere, so nothing here is brand-scale and there is nothing for
    these counts to disagree with. See DECISIONS.md "Panel-measured households, not
    brand-scale".

    With a sku it computes the same flow for that one item. Columns: from_index,
    from_label, to_label, prior_buyers, current_buyers, retained, new, lapsed,
    net (= new − lapsed). Identities hold every row (prior = retained + lapsed;
    current = retained + new).
    """
    from cinderhaven_household_panel import get_quarters

    tx = _tx(product_line, retailer_id, sku)
    quarters = get_quarters()[["quarter_index", "label"]].sort_values("quarter_index")
    buyers_by_q = {qi: set(g["household_id"].unique()) for qi, g in tx.groupby("quarter_index")}
    labels = dict(zip(quarters["quarter_index"], quarters["label"]))
    indices = quarters["quarter_index"].tolist()

    rows = []
    for prev, curr in zip(indices[:-1], indices[1:]):
        prior = buyers_by_q.get(prev, set())
        current = buyers_by_q.get(curr, set())
        retained = len(prior & current)
        new = len(current - prior)
        lapsed = len(prior - current)
        rows.append({
            "from_index": prev,
            "from_label": labels[prev],
            "to_label": labels[curr],
            "prior_buyers": len(prior),
            "current_buyers": len(current),
            "retained": retained,
            "new": new,
            "lapsed": lapsed,
            "net": new - lapsed,
        })
    return pd.DataFrame(rows)


# ── Per-item verdict: promotion or brand? ─────────────────────────────
# Verdict labels. "No data" is distinct from "Promotion": a filter that excludes an
# item (or leaves all its triers immature) must NOT read as a failed launch.
VERDICT_BRAND = "Brand"
VERDICT_PROMOTION = "Promotion"
VERDICT_NO_DATA = "No data"


def item_verdict(window_weeks: int, threshold: float, product_line: str | None = None,
                 retailer_id: str | None = None) -> pd.DataFrame:
    """Trial reach vs mature repeat rate per launch item, with a promotion/brand verdict.

    A trial-heavy, repeat-light item (repeat below ``threshold``) reads as a promotion;
    at or above threshold it reads as a brand. When no mature triers exist for the item
    under the current filter, the verdict is "No data" (repeat_rate is not meaningful),
    never a false "Promotion". Columns: sku_id, role, line_name, launch_label, n_triers,
    trial_reach, n_mature, repeat_rate, verdict.

    ``line_name`` is the human product-line name (e.g. "Snack Bites") so exec-facing
    copy can name an item without exposing the internal SKU code.
    """
    rows = []
    for sku, cfg in panel.LAUNCH_ITEMS.items():
        summary = repeat_summary(window_weeks, product_line, retailer_id, sku=sku)
        repeat_rate = summary["repeat_rate"]
        if summary["n_mature"] == 0:
            verdict = VERDICT_NO_DATA
        elif repeat_rate >= threshold:
            verdict = VERDICT_BRAND
        else:
            verdict = VERDICT_PROMOTION
        line_code = sku.split("-")[1]
        rows.append({
            "sku_id": sku,
            "role": cfg["role"],
            "line_name": panel.PRODUCT_LINES[line_code]["name"],
            "launch_label": panel.QUARTERS.loc[cfg["launch_quarter_index"], "label"],
            "n_triers": summary["n_triers"],
            "trial_reach": summary["n_triers"] / N_HOUSEHOLDS,
            "n_mature": summary["n_mature"],
            "repeat_rate": repeat_rate,
            "verdict": verdict,
        })
    return pd.DataFrame(rows)
