"""Client-mode CLI for Trial vs Repeat (Leaky Bucket).

Separates real adoption from expensive sampling on a client's own household-panel
transactions: how many households tried the brand, and how many came back within
the repeat window. Runs locally via the shared ``lailara_engagement`` scaffold.

The credibility make-or-break is right-censoring: recent triers who have not yet
had a full repeat window are **excluded** from the repeat rate (not counted as
non-repeaters). This replicates the tested engine's maturity cutoff
(``app/trial_repeat.py::repeat_summary``) exactly, and the cutoff date is stated
on the deliverable.

Grain note: this is a **household-panel** tool, not store-POS — so it does NOT use
the POS scan contract. It reads a panel-transaction file (household_id,
purchase_date [, product_line]) through the generic ``lailara_engagement`` specs.

Required input: **transactions** — one row per purchase. Required config:
``basis.repeat_window_weeks``. A missing required column blocks with a branded
Data Readiness Report; a clean run writes a draft-watermarked, provenance-footed
**Trial vs Repeat Summary** (HTML) to ``client-output/``.

Usage:
    python client_mode.py --config engagement.yml --input client-data/transactions.csv \
        [--out client-output] [--final]
"""

from __future__ import annotations

import argparse
import html
from pathlib import Path

import pandas as pd

from lailara_engagement import (
    ColumnSpec,
    ConfigError,
    PreflightSpec,
    build_provenance,
    load_config,
    read_table,
    run_preflight,
    validation_status_label,
    write_report,
)
from lailara_engagement import palette as P
from lailara_engagement.pos import to_frame
from lailara_engagement.provenance import Provenance

TOOL = "trial-vs-repeat"
TOOL_VERSION = "1.0"


def resolve_window_weeks(config) -> int:
    v = (config.basis or {}).get("repeat_window_weeks") or config.raw.get("repeat_window_weeks")
    if v is None:
        raise ConfigError(["`basis.repeat_window_weeks` is required — the repeat window "
                           "(e.g. 8 or 12 weeks) drives the maturity cutoff and the repeat rate"])
    try:
        w = int(v)
    except (TypeError, ValueError):
        raise ConfigError([f"`basis.repeat_window_weeks` must be an integer, got {v!r}"]) from None
    if w <= 0:
        raise ConfigError(["`basis.repeat_window_weeks` must be positive"])
    return w


def _transactions_spec() -> PreflightSpec:
    return PreflightSpec(tool=TOOL, version=TOOL_VERSION, columns=[
        ColumnSpec(name="household_id", dtype="identifier", required=True,
                   description="panel household id", spec_ref="INPUT-SPEC §Transactions"),
        ColumnSpec(name="purchase_date", dtype="date", required=True,
                   description="purchase date; first purchase = the trial event", spec_ref="INPUT-SPEC §Transactions"),
        ColumnSpec(name="product_line", dtype="string", required=False, allow_blank=True,
                   description="optional slice for a per-line breakdown", spec_ref="INPUT-SPEC §Transactions"),
    ])


def compute_trial_repeat(tx: pd.DataFrame, window_weeks: int, as_of: pd.Timestamp) -> dict:
    """Trial + maturity-cutoff repeat rate, matching app/trial_repeat.py::repeat_summary.

    A trier is mature when a full window has elapsed since their first purchase
    (first_date + window <= as_of); only mature triers count toward the rate. A
    trier repeats if any purchase is strictly after their first and within the
    window.
    """
    win = pd.Timedelta(weeks=window_weeks)
    fp = (tx.sort_values("purchase_date", kind="stable")
          .drop_duplicates("household_id", keep="first")[["household_id", "purchase_date"]]
          .rename(columns={"purchase_date": "first_date"}))
    mature = fp[fp["first_date"] + win <= as_of]
    n_immature = len(fp) - len(mature)
    if len(mature):
        joined = tx.merge(mature, on="household_id")
        in_window = ((joined["purchase_date"] > joined["first_date"])
                     & (joined["purchase_date"] <= joined["first_date"] + win))
        repeated = joined.assign(r=in_window).groupby("household_id")["r"].any()
        n_repeaters = int(repeated.sum())
        repeat_rate = n_repeaters / len(mature)
    else:
        n_repeaters, repeat_rate = 0, 0.0
    return {
        "n_triers": int(len(fp)), "n_mature": int(len(mature)), "n_immature": int(n_immature),
        "n_repeaters": n_repeaters, "repeat_rate": round(repeat_rate, 4),
        "maturity_cutoff_date": (as_of - win).date().isoformat(), "window_weeks": window_weeks,
    }


def _deliverable_html(config, overall, by_line, window_weeks, provenance: Provenance,
                      limitations, *, draft: bool) -> str:
    esc = html.escape
    draft_class = " ll-draft" if draft else ""
    line_rows = "".join(
        f"<tr><td>{esc(k)}</td><td class=num>{v['n_mature']}</td>"
        f"<td class=num>{v['n_repeaters']}</td><td class=num>{v['repeat_rate']*100:.1f}%</td></tr>"
        for k, v in by_line.items()
    )
    line_section = f"""
<section class=ll-section><h2 class=ll-h2>By product line</h2>
<table class=ll-table><thead><tr><th>Product line</th><th>Mature triers</th><th>Repeaters</th>
<th>Repeat rate</th></tr></thead><tbody>{line_rows}</tbody></table></section>""" if by_line else ""
    lim = "".join(f"<li>{esc(x)}</li>" for x in limitations)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Trial vs Repeat Summary — {esc(config.client_name)}</title><style>{_css(draft)}</style></head>
<body class="{draft_class.strip()}"><main class=ll-page>
<header class=ll-header>
  <div class=ll-eyebrow>Lailara LLC · Trial vs Repeat</div>
  <h1 class=ll-title>Trial vs Repeat Summary</h1>
  <div class=ll-client>
    <div><span class=ll-k>Client</span> {esc(config.client_name)}</div>
    <div><span class=ll-k>Engagement</span> {esc(config.engagement_id)}</div>
    <div><span class=ll-k>As of</span> {esc(config.as_of_date.isoformat())}</div>
    <div><span class=ll-k>Prepared by</span> {esc(config.prepared_by)}</div>
  </div>
</header>
<section class=ll-banner>
  <div class=ll-score>{overall['repeat_rate']*100:.1f}% repeat within {window_weeks} weeks</div>
  <div>{overall['n_triers']:,} triers · {overall['n_mature']:,} mature · {overall['n_repeaters']:,} repeated
       · {overall['n_immature']:,} too recent to judge (excluded)</div>
  <div class=ll-basis>Basis: panel-measured households (not projected to brand scale).
       Right-censoring: triers whose first purchase is after {esc(overall['maturity_cutoff_date'])}
       have not had a full {window_weeks}-week window and are excluded from the rate — not counted as non-repeaters.</div>
</section>
{line_section}
<section class=ll-section>
  <h2 class=ll-h2>Data limitations</h2>
  <ul class=ll-limitations>{lim}</ul>
</section>
{provenance.to_html()}
</main></body></html>"""


def _css(draft: bool) -> str:
    draft_css = (
        ".ll-draft::before{content:'DRAFT';position:fixed;top:50%;left:50%;"
        "transform:translate(-50%,-50%) rotate(-32deg);font-family:var(--s);"
        "font-size:22vw;font-weight:700;color:rgba(204,16,10,.06);z-index:0;"
        "pointer-events:none;white-space:nowrap}" if draft else ""
    )
    return f"""
:root{{--s:{P.LL_SERIF};--f:{P.LL_SANS}}}
*{{box-sizing:border-box}}
body{{margin:0;background:{P.LL_CANVAS};color:{P.LL_TEXT};font-family:var(--f);line-height:1.6}}
.ll-page{{position:relative;z-index:1;max-width:{P.LL_MAX_WIDTH};margin:0 auto;padding:48px 24px}}
.ll-header{{border-bottom:1px solid {P.LL_GRIDLINE};padding-bottom:24px;margin-bottom:24px}}
.ll-eyebrow{{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:{P.LL_RED};font-weight:600}}
.ll-title{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:34px;margin:8px 0 16px}}
.ll-client{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 24px;font-size:14px}}
.ll-k{{display:block;color:{P.LL_TEXT_SEC};font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.ll-banner{{border-radius:2px;padding:16px 20px;margin-bottom:32px;background:{P.LL_HK_SURFACE};color:{P.LL_HK_DARK}}}
.ll-score{{font-family:var(--s);font-weight:700;font-size:22px}}
.ll-basis{{font-size:12px;color:{P.LL_TEXT_SEC};margin-top:8px}}
.ll-section{{margin:0 0 32px}}
.ll-h2{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:22px;
margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.ll-table{{width:100%;border-collapse:collapse;font-size:14px}}
.ll-table th{{text-align:left;background:{P.LL_CHICAGO};color:#fff;padding:8px 12px}}
.ll-table td{{padding:8px 12px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.ll-limitations{{margin:0;padding-left:20px}}.ll-limitations li{{margin-bottom:6px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.ll-provenance{{margin-top:40px;background:{P.LL_CARD_BG};color:{P.LL_CARD_TEXT};
padding:20px 24px;border-radius:2px;font-size:13px}}
.ll-prov-title{{font-family:var(--s);font-weight:700;font-size:16px;margin-bottom:8px}}
.ll-provenance div{{margin-bottom:4px;color:{P.LL_CARD_SUBTITLE}}}
.ll-provenance strong{{color:{P.LL_CARD_TEXT}}}
.ll-prov-inputs{{width:100%;border-collapse:collapse;margin-top:8px}}
.ll-prov-inputs th{{text-align:left;border-bottom:1px solid rgba(255,255,255,.12);padding:4px 8px;color:{P.LL_CARD_MUTED}}}
.ll-prov-inputs td{{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,.08);color:{P.LL_CARD_SUBTITLE}}}
.ll-prov-brand{{margin-top:12px;font-family:var(--s);color:{P.LL_CARD_MUTED}}}
{draft_css}
@media print{{body{{background:#fff}}}}
"""


def run(config_path: str, input_path: str, out_dir: str, *, final: bool = False) -> dict:
    config = load_config(config_path)
    window_weeks = resolve_window_weeks(config)
    read = read_table(input_path)
    spec = _transactions_spec()
    report = run_preflight(read, spec, config)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    provenance = build_provenance(
        tool=TOOL, tool_version=TOOL_VERSION, inputs=[read], config=config,
        validation_status=validation_status_label(report.status, report.n_warnings),
        extra={"Grain": "household panel (not store POS)", "Repeat window": f"{window_weeks} weeks"})
    if not report.passed:
        paths = write_report(report, config, str(out), provenance=provenance, draft=not final,
                             basename="data-readiness-report", title="Trial-vs-Repeat Data Readiness Report")
        return {"status": "blocked", "readiness_report": paths["html"]}

    tx = to_frame(read, report, spec)
    as_of = pd.Timestamp(config.as_of_date)
    overall = compute_trial_repeat(tx, window_weeks, as_of)
    by_line = {}
    if "product_line" in tx.columns:
        for line, g in tx.groupby(tx["product_line"].fillna("(unspecified)")):
            if str(line).strip():
                by_line[str(line)] = compute_trial_repeat(g, window_weeks, as_of)

    limitations = [f.message for f in report.findings if f.severity == "warning"]
    if overall["n_immature"]:
        limitations.append(f"{overall['n_immature']} trier(s) too recent to judge "
                           f"(first purchase after {overall['maturity_cutoff_date']}) — excluded from the rate.")
    if not limitations:
        limitations.append("No warnings — the transaction file passed preflight cleanly.")

    html_path = out / "trial-vs-repeat-summary.html"
    html_path.write_text(_deliverable_html(config, overall, by_line, window_weeks,
                                            provenance, limitations, draft=not final), encoding="utf-8")
    return {"status": "ok", **overall, "report": str(html_path), "n_warnings": report.n_warnings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trial-vs-repeat client mode")
    ap.add_argument("--config", required=True); ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="client-output"); ap.add_argument("--final", action="store_true")
    args = ap.parse_args(argv)
    result = run(args.config, args.input, args.out, final=args.final)
    if result["status"] == "blocked":
        print(f"BLOCKED — data not ready. See {result['readiness_report']}")
        return 3
    print(f"{result['repeat_rate']*100:.1f}% repeat within {result['window_weeks']}w · "
          f"{result['n_mature']:,} mature triers, {result['n_immature']:,} excluded (too recent)")
    print(f"report -> {result['report']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
