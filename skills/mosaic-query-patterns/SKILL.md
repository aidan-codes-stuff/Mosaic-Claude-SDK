---
name: mosaic-query-patterns
description: Use this skill any time you'll write SQL against a Mosaic semantic model via the Mosaic MCP query tool (mcp__*__query, mcp__*__get_semantics, mcp__*__get_mosaic_models). That includes answering business questions backed by a Mosaic model; debugging Mosaic query errors ("must be aggregate or in GROUP BY", "Column X cannot be resolved", "intermediate rows exceeds maximum", "Could not serialize data to JSON", "defaultValue is null", "ERR001"); building a dashboard, chart, or analysis backed by a Mosaic model; explaining a Mosaic result that looks wrong (often snapshot-metric inflation or cross-table fan-out). Load this skill BEFORE writing the first Mosaic query. Mosaic's metric resolution and join behavior are non-obvious and queries written without these patterns produce silently wrong numbers.
---

# Mosaic Query Patterns

This skill applies to the Mosaic MCP `query` tool only. The REST API and natural-language endpoints have a separate planner pre-pass and may behave differently.

## Pre-flight checklist

Before writing any query, confirm you have done all of the following:

- Called `get_semantics` for the target model — column names and metric classes cannot be guessed
- Identified the aggregation type for every metric you plan to use (see Metric Classes below)
- Confirmed whether any metrics originate from different source tables (fan-out risk)
- Used the `"form__attribute"` input name form — output display headers from prior results are NOT valid input names

## Column naming

Input form is always `"dimension__attribute"` (double underscore). Bare attribute names fail silently or error.

```sql
-- correct
SELECT "category__category_name" FROM "<model_name>" ...

-- errors: Column 'category_name' cannot be resolved
SELECT "category_name" FROM "<model_name>" ...
```

Output column headers come back as `attribute (attribute)` — display-only. Do NOT copy that form back into a follow-up query.

Identifier quoting is double-quotes only. Backticks are not supported.

## Metric classes — most important section

Call `get_semantics` and identify which class each metric belongs to before writing a GROUP BY query. Wrong aggregation wrappers produce silently wrong numbers.

**Class 1 — sum-defined** (`sum(table.col)`): behaves as the bare source column. You MUST wrap in `SUM()` or another aggregation in GROUP BY queries. Without it the query errors with "must be aggregate or in GROUP BY".

**Class 2 — count-defined** (`count(table.id)`): collapses to global count regardless of wrapper. `SUM`, `MAX`, `MIN` all return the same value.

**Class 3 — avg-defined** (`avg(table.col)`): same collapse behavior as Class 2. `SUM` around an avg-defined metric returns the global average, not a sum.

**Class 4 — additive calc** (e.g., `{Metric A} - {Metric B}` where both are sum-style): treat as Class 1. Wrap in `SUM()`. Additive across groups.

**Class 5 — ratio calc** (e.g., `{Numerator} / {Denominator}`): always pre-aggregated to the in-scope universe. `SUM`/`AVG`/`MIN`/`MAX` all return the same value per GROUP BY scope. Never sum ratios across groups manually.

**Default rule when unsure:** always wrap in `SUM()`. Correct for Classes 1 and 4, harmless for 2, 3, and 5.

## GROUP BY rules

Every non-metric column in SELECT must appear in GROUP BY (Trino standard). Ordinal references (`GROUP BY 1, 2, 3`) work.

When grouping by an attribute below the metric's grain, the metric fans out. A `transaction count` metric defined at the transaction grain will over-count when grouped by a child line-item attribute — every transaction appears once per line item.

Use `COUNT(DISTINCT "<primary_key_attr>")` when you need true unique counts at any grain.

## Cross-table CASE GROUP BY (fan-out foot-gun)

When a CASE expression references an attribute from one fact table and the rest of the query references attributes from another, you can get a cartesian fan-out: every CASE bucket appears for every value of the unrelated attribute.

Verify with a control query first — a single grouping that should naturally distinguish the buckets. If both buckets show all values, fan-out is happening. Fix by:

- Filtering both attributes to the same source table
- Wrapping in a CTE that materializes the bucketed dimension first
- Restricting the grouped attribute to one with a clear hierarchy to the CASE attribute

## Date handling

`DATE_TRUNC('week', ts)` may be Sunday-based on some clusters. Probe before assuming Monday-style buckets:

```sql
SELECT DATE_TRUNC('week', DATE '2025-04-08') AS week_start
-- 2025-04-06 = Sunday-based cluster
-- 2025-04-07 = Monday-based cluster
```

For date filtering on timestamp columns, both forms below are equivalent:

```sql
WHERE "<date_col>" >= TIMESTAMP '2025-04-01 00:00:00'
  AND "<date_col>" <  TIMESTAMP '2025-04-29 00:00:00'

-- equivalent
WHERE CAST("<date_col>" AS date) BETWEEN DATE '2025-04-01' AND DATE '2025-04-28'
```

Prefer hard-coded literals over `CURRENT_DATE` chained with `DATE_TRUNC` until you've confirmed week-start config.

A `DATE_TRUNC('week', ...)` GROUP BY will return more buckets than the filter range implies if the range doesn't align to week boundaries. A 21-day window starting mid-week produces 4 weekly buckets (partial first and last, 2 full). Align filter range to week-start if you need exactly N buckets.

## Snapshot metric inflation

Some models define snapshot metrics (balances, prices, inventory levels, share counts) with `sum(...)` aggregation. SUM is the wrong aggregation for snapshots — it inflates by the number of snapshots in the result set.

Symptom: a number that is 10x–1000x larger than expected. A daily-snapshot table with 30 days of history will inflate a balance metric by roughly 30.

Workaround: filter to a single date with `WHERE "<date_col>" = DATE '<latest>'` before aggregating. Or use `MAX` if the value is monotonically increasing.

Long-term fix is at the model level: the metric definition should be changed from `sum()` to `last()` or `max()`, or the model should enforce a required date filter. Flag to the model owner.

## CASE bucketing over CAST(date) — `defaultValue is null` bug

A `CASE WHEN CAST("date_col" AS date) BETWEEN ... THEN 'label' ... END` used as a GROUP BY bucket fails with the opaque error:

```
defaultValue is null
```

Likely cause: planner null-handling when a CASE expression over a CAST date column has an implicit `ELSE NULL` branch and not every row matches a WHEN branch.

**Workaround: UNION ALL of separately-filtered queries.** Each branch uses a hard date filter in WHERE, eliminating the derived bucket column and the implicit NULL branch entirely:

```sql
SELECT 'Last Week' AS period,
       SUM("net revenue") AS net_revenue,
       SUM("order count") AS orders
FROM "omnichannel retail pulse"
WHERE CAST("order date__order date" AS date) BETWEEN DATE '2026-04-27' AND DATE '2026-05-03'
UNION ALL
SELECT 'Prior Week' AS period,
       SUM("net revenue"),
       SUM("order count")
FROM "omnichannel retail pulse"
WHERE CAST("order date__order date" AS date) BETWEEN DATE '2026-04-20' AND DATE '2026-04-26'
```

If you must keep CASE, try these in order:
1. Add an explicit `ELSE 'Other'` branch to eliminate the implicit NULL fallthrough
2. Filter WHERE to only rows that match a WHEN branch, so CASE never evaluates to NULL
3. Replace CASE bucketing with `DATE_TRUNC('week', ...)` after confirming week-start config

## Cardinality blowup

Unconstrained queries against multi-table models can fail with:

```
ERR001 ... The number of intermediate rows exceeds the maximum ...
```

The model joins all tables flat at query time. Fix: add WHERE filters, reference specific attributes in SELECT, or use `COUNT(DISTINCT <primary_key_attr>)` instead of `COUNT(*)`.

## Error quick-reference

| Error message | Cause | Fix |
|---|---|---|
| `'"X"' must be an aggregate expression or appear in GROUP BY` | Bare metric in GROUP BY query | Wrap in `SUM()` |
| `Column 'X' cannot be resolved` | Used display form instead of `"dim__attr"` | Use full `form__attribute` input name |
| `ERR001 ... intermediate rows exceeds maximum` | Cardinality blowup on unconstrained join | Add WHERE filters or use DISTINCT |
| `Could not serialize data to JSON` | Null timestamp + null metrics in result row | Filter null timestamps in WHERE |
| `defaultValue is null` | CASE over `CAST("col" AS date)` with implicit NULL branch in GROUP BY | Switch to UNION ALL of single-range queries or add explicit `ELSE` |

## Safe patterns (verified)

```sql
-- 1. Single metric, no GROUP BY
SELECT SUM("metric") AS m FROM "<model>"

-- 2. Metric by single attribute
SELECT "dim__attr", SUM("metric") AS m
FROM "<model>"
GROUP BY "dim__attr"
ORDER BY m DESC
LIMIT 50

-- 3. Multiple metrics, multi-attribute GROUP BY
SELECT "dim__attr1", "dim__attr2", SUM("metric1") AS m1, SUM("metric2") AS m2
FROM "<model>"
GROUP BY 1, 2
LIMIT 100

-- 4. CASE bucket (single-table attribute — no cross-table risk)
SELECT CASE WHEN "dim__attr" IN ('A','B') THEN 'Group1' ELSE 'Group2' END AS bucket,
       SUM("metric") AS m
FROM "<model>"
GROUP BY 1

-- 5. Date-bucketed time series
SELECT DATE_TRUNC('month', "date_col__date_col") AS period,
       SUM("metric") AS m
FROM "<model>"
WHERE "date_col__date_col" >= DATE '2025-01-01'
GROUP BY 1
ORDER BY 1
LIMIT 24

-- 6. HAVING clause
SELECT "dim__attr", SUM("metric") AS m
FROM "<model>"
GROUP BY "dim__attr"
HAVING SUM("metric") > 1000000

-- 7. ROLLUP for subtotals
SELECT "dim__attr1", "dim__attr2", SUM("metric") AS m
FROM "<model>"
GROUP BY ROLLUP ("dim__attr1", "dim__attr2")

-- 8. Period comparison without CASE (avoids defaultValue is null)
SELECT 'Current' AS period, SUM("metric") AS m
FROM "<model>"
WHERE CAST("date_col__date_col" AS date) BETWEEN DATE '2026-04-27' AND DATE '2026-05-03'
UNION ALL
SELECT 'Prior' AS period, SUM("metric") AS m
FROM "<model>"
WHERE CAST("date_col__date_col" AS date) BETWEEN DATE '2026-04-20' AND DATE '2026-04-26'
```

## Patterns to avoid until verified

- CASE on an attribute from one source table while GROUPing by attributes from a different source table — fan-out risk, verify with a control query first
- Bare metric in SELECT with no GROUP BY against a multi-table model — can return millions of rows
- `SELECT *` against any multi-table model — cardinality blowup likely
- `SUM` wrapping a snapshot metric without a date filter — inflates by snapshot count
- Comparing a ratio calc metric's grouped sum to the global value as a correctness check — ratios don't sum across groups by design

## When to escalate to the model owner

If a metric behaves wrong at every aggregation level, the model definition is likely the root cause — not the query. Check the semantic response: if a price, balance, or rating metric is defined as `sum(...)`, that's the source of the wrong answer. If a metric should be additive but doesn't roll up to the global value across groups, the calc expression may not be aggregating in the right join scope. In both cases, flag to the model owner rather than working around it indefinitely in SQL.
