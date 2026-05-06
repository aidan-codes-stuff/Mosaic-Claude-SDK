---
name: mosaic
description: How to reason about Mosaic — Strategy Software's governed semantic layer — and how to sequence the four Mosaic MCP tools (get_projects, get_mosaic_models, get_semantics, query) to answer business-data questions correctly.
---

# Mosaic skill

You have access to Mosaic, Strategy Software's governed semantic layer. The instructions below tell you how to think about Mosaic, what tools to call in what order, and the non-obvious facts you need to know to write a query that works.

## 1. What Mosaic is

Mosaic sits between enterprise data sources (Snowflake, Databricks, SAP, Postgres, and more) and you, the agent. It exposes that data as **governed metrics** — pre-defined aggregations and KPIs whose business logic has already been reviewed and validated by the customer's analysts.

Always prefer a Mosaic-defined metric over an ad-hoc `SUM()` / `AVG()` / `COUNT()` over raw columns. The metrics encode invariants you don't have — fiscal calendar boundaries, customer-segment carve-outs, revenue-recognition rules, exclusion lists. Re-deriving them with raw SQL almost always produces a number that disagrees with the customer's dashboards.

## 2. The canonical tool call sequence

You **must** follow this order. Skipping a step will produce wrong answers or malformed SQL.

1. **`get_projects`** — find which project the user's question relates to. If the user mentions a business area (e.g., "customer churn", "inventory", "marketing campaigns"), map it to a project name returned here.
2. **`get_mosaic_models(project=...)`** — list the models (logical tables) inside that project. Pick the most relevant model. If multiple models could plausibly answer the question, ask the user.
3. **`get_semantics(project=..., model=...)`** — read the full semantic definition of the chosen model **before writing any SQL**. This is non-negotiable. Column names follow a non-guessable convention (see Section 3) and metric definitions are how you avoid re-deriving validated logic.
4. **`query(project=..., query=...)`** — before writing SQL, load the **`mosaic-query-patterns`** skill. It contains the metric class rules, fan-out patterns, known bugs, and safe SQL templates you need to produce correct results. Then write and execute read-only Trino SQL using the column names you saw in `get_semantics`.

If the user's question is broad ("what data do I have?"), stop after step 1 or 2 and summarize, rather than guessing a query.

## 3. Column naming rules — CRITICAL

These are the core rules. Full detail, safe patterns, and known failure modes live in `mosaic-query-patterns`.

- **Attribute columns** follow the form `<form>__<name>` — two underscores between form and attribute name. Example: `customer name__customer name`, `campaign__campaign id`, `product__sku`. Bare attribute names without the form prefix will fail.
- **Always wrap column and table names in double quotes.** Backticks are **not** supported by the Trino backend.
- **Date attributes may expose pre-bucketed `(day interval)` / `(month interval)` / `(quarter interval)` / `(year interval)` pseudo-columns.** When a model exposes them (check `get_semantics`), prefer those for time-grouped aggregations — they encode the model's calendar config. When they're absent, fall back to the `DATE_TRUNC` patterns in `mosaic-query-patterns` (and probe for week-start config as that skill describes).
- **Never `SELECT *`** — be explicit about every column. **Always include `LIMIT N`** (typically 100 or fewer).

## 4. Metric vs. attribute disambiguation

When the user asks for something like "give me revenue" and the model has multiple revenue metrics (e.g., `gross revenue`, `net revenue`, `recognized revenue`), **do not pick silently**. Surface the options:

> "I see three revenue metrics in this model: gross revenue, net revenue, recognized revenue. Which should I use?"

Same rule for attributes that have multiple forms (e.g., `customer name`, `customer id`, `customer email` are all forms of the `customer` attribute). When in doubt, ask.

## 5. Error recovery

The MCP server returns errors with stable codes. Map them to actions:

| Error code | What it means | What to do |
|---|---|---|
| `MOSAIC_PROJECT_NOT_FOUND` | The `project` arg doesn't match any accessible project. | Call `get_projects` and retry with a valid name. |
| `MOSAIC_MODEL_NOT_FOUND` | The `model` arg doesn't exist in that project. | Call `get_mosaic_models(project=...)` and retry. |
| `MOSAIC_SQL_SYNTAX` | Trino parse error. | Inspect `details.parser_message`, rewrite the query, retry. |
| `MOSAIC_SQL_TABLE_NOT_FOUND` | The table referenced in SQL doesn't exist in the schema. | Call `get_mosaic_models` to re-check table names. Remember model names with spaces must be double-quoted. |
| `MOSAIC_SQL_COLUMN_NOT_FOUND` | A referenced column doesn't exist. | Call `get_semantics` again. Remember the `<form>__<name>` convention. |
| `MOSAIC_SEMANTICS_UNAVAILABLE` | Server reached but metadata fetch failed. | Retry once. If it persists, tell the user the model's metadata is currently unavailable and ask them to check the model in the Strategy UI. Do not retry more than twice. |
| `MOSAIC_AUTH_INVALID` | Token expired or missing scope. | Tell the user their Mosaic session has expired and ask them to reconnect via the plugin settings. |
| `MOSAIC_SQL_WRITE_REJECTED` | Statement is INSERT / UPDATE / DELETE / MERGE / CREATE / DROP. | The connector is read-only. Tell the user to use the Strategy UI for writes. |
| `MOSAIC_QUERY_TIMEOUT` | SQL exceeded server timeout. | Add a `LIMIT`, narrow the time range, or replace ad-hoc aggregation with a pre-defined metric from `get_semantics`. |
| `MOSAIC_RATE_LIMITED` | Per-user QPS exceeded. | Wait `details.retry_after_seconds` and retry. |
| `MOSAIC_INTERNAL` | Anything not classified above. | Retry once. If it persists, surface to the user — don't retry indefinitely. |

## 6. What Mosaic is NOT

- **Not a write API.** Don't try to `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, or `DROP`. They will be rejected.
- **Not a raw SQL engine.** The value is in governed metrics. Always prefer reading `get_semantics` and using a pre-defined metric over hand-rolling aggregations.
- **Not a document search.** For unstructured questions ("what did the CEO say in the all-hands?"), say so — Mosaic only answers structured business-data questions.
