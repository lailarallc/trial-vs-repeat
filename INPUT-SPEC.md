# Trial vs Repeat (Leaky Bucket) — Client Data Input Specification

Separates real adoption from expensive sampling on your household-panel
transactions: how many households tried the brand, and how many came back within
the repeat window. It is a **household-panel** tool (not store-POS), so it reads a
panel-transaction file through the generic `lailara_engagement` specs.

The credibility make-or-break is **right-censoring**: triers whose first purchase
is too recent to have had a full repeat window are excluded from the rate — never
counted as non-repeaters. The maturity cutoff date is stated on the deliverable.

## §Transactions — the panel purchase ledger (required)
One row per purchase.

| Column | Type | Required | Used for |
|---|---|---|---|
| `household_id` | identifier (text) | **required** | trial (first purchase) + repeat |
| `purchase_date` | date | **required** | first purchase = trial; maturity + in-window repeat |
| `product_line` | string | optional | a per-product-line breakdown |

First purchase per household = the trial event. A trier is **mature** when a full
window has elapsed since first purchase (`first_date + window ≤ as_of_date`); only
mature triers count. A trier **repeats** if any purchase is strictly after their
first and within the window. Repeat rate = repeaters ÷ mature triers.

## Required declaration (`basis.repeat_window_weeks`)
The repeat window (e.g. 8 or 12 weeks). Drives the maturity cutoff and the repeat
rate; carried into the provenance footer.

## Column mapping (`engagement.yml`)
```yaml
client: {name: Your Brand}
engagement: {id: YB-2026-08}
as_of_date: 2026-06-30
basis:
  repeat_window_weeks: 12
inputs:
  input: client-data/transactions.csv
columns:
  household_id: "Panelist ID"
  purchase_date: "Purchase Date"
```
