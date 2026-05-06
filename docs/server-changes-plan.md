# Mosaic MCP Server — Changes Required for External Plugin Publishing

**Status:** Pending eng implementation. Companion to https://github.com/aidan-codes-stuff/Mosaic-Claude-SDK.

**Audience:** Mosaic MCP server engineering team.

## Overview

Three workstreams of server-side changes are needed before the Mosaic Connect plugin can be listed on the Anthropic plugin marketplace. They are ordered by implementation risk:

1. **Workstream B — Tool schemas (rename + rewrites).** Highest impact, lowest risk. An LLM agent reading the current tool descriptions will fail to sequence calls correctly and will generate malformed SQL. **Land this first.**
2. **Workstream C — Error model.** Medium effort. Errors today are inconsistent (sometimes in MCP error field, sometimes in success output), leak internal SQL, and have no machine-readable codes.
3. **Workstream A — Auth verification + small additions.** Mostly already built — the remaining items are verification and small code additions.

This repo (the SDK plugin) ships independently of these server changes. The integration tests document current server behavior; when each workstream lands, the corresponding tests need to be updated (the test files contain `NOTE:` comments marking each spot).

---

## Workstream A — Auth (verification + small additions)

| # | Item | Type | Notes |
|---|---|---|---|
| A1 | Verify first-connect redirect from vanilla Claude Agent SDK (non-Cowork) | Verification | Stand up a clean Claude Agent SDK env, install the plugin, walk the redirect. Capture user-visible behavior at each step. |
| A2 | 30-day token expiry → surfaces as `MOSAIC_AUTH_INVALID` | Spec + small code | At day 31, the next tool call must return the MCP error field with code `MOSAIC_AUTH_INVALID`, message "Your Mosaic session has expired. Reconnect via plugin settings.", and a `recovery_hint`. Must NOT be a silent failure or a mid-session redirect — expiry must be visible to the user. |
| A3 | `environment_url` in plugin config | Small code | The plugin manifest (this repo's `plugin.json`) declares an `environment_url` config field. The server's redirect target and token audience must use this value. |
| A4 | Read-only enforcement on `query` (AST-level) | Small code | Add a pre-execution check: reject any statement whose root is not `SELECT` / `WITH` / `EXPLAIN` / `SHOW` / `DESCRIBE`. Return `MOSAIC_SQL_WRITE_REJECTED` (see Workstream C error taxonomy). Makes read-only a tool-shape contract visible to the agent, not a hidden RBAC behavior. |
| A5 | Bug #1 — schema scope on table-less queries | Verification | `query(schema="nonexistent_schema", query="SELECT 1")` currently succeeds. Confirm named-user RBAC enforces scope at the auth/session boundary independent of SQL parse. If not, add explicit scope validation. |
| A6 | Auth-flow doc for marketplace reviewers | Docs | See [`docs/auth-flow.md`](./auth-flow.md) in this repo. Eng should review for accuracy. |

---

## Workstream B — Tool schemas (rename + rewrites)

This is the **highest-priority** change. An LLM agent reading the current tool descriptions will fail to sequence calls correctly and will generate malformed SQL.

### Cross-cutting changes (apply to all four tools)

1. **Rename parameter `schema` → `project`** in all tool `inputSchema` definitions. Keep `schema` as a deprecated alias in the handler for one full release (see backward-compat pseudocode below). **Do NOT advertise the deprecated alias in `inputSchema`** — keep the agent surface clean.
2. **Rename parameter `table` → `model`** in `get_semantics`. Same deprecation pattern.
3. **Add a server-level `instructions` field** to the `initialize` response. Paste the full text from the "Server-level instructions" section in `mosaic-mcp-tool-descriptions.md` (the v2 copy document maintained by the docs team) verbatim.

### Per-tool description replacements

For each of the four tools (`get_projects`, `get_mosaic_models`, `get_semantics`, `query`), copy the exact description text and `inputSchema` from `mosaic-mcp-tool-descriptions.md`. **That document is the source of truth for Workstream B copy. Do not paraphrase.**

### Server-side response shape changes (ship with Workstream B)

- **`get_mosaic_models` no-args response:** drop the duplicated project list that currently precedes the model list. The agent has already seen the project list from `get_projects`; repeating it confuses tool-call sequencing.
- **`get_semantics` response:** prepend a one-line legend explaining the `<form>__<name>` convention and the `(day/month/quarter/year interval)` pseudo-columns. The legend is what makes the response self-documenting to the agent — without it, the agent has to infer the convention from examples.
- **Source identifier redaction decision:** metric formulas currently expose source file paths (e.g., `customer_health_marketing_attributes - Copy.xlsx.Churn_Risk_Score`). Eng decision required before external publish: redact or keep? **Recommendation:** make it configurable. Default: **keep** (aids LLM grounding by giving the model concrete column lineage).

### Backward-compat handler pseudocode

```python
def get_mosaic_models(project: str | None = None, schema: str | None = None) -> str:
    if schema is not None and project is None:
        log.warning("Deprecated parameter 'schema' used; rename to 'project'. schema=%s", schema)
        project = schema
    elif schema is not None and project is not None:
        log.warning("Both 'project' and 'schema' provided; using 'project', ignoring 'schema'.")
    return _list_models(project=project)
```

Apply the same pattern to `get_semantics` (also aliasing `table` → `model`) and to `query`.

### Removal timeline

Keep deprecated aliases for **at least one release after Cowork's internal prompts are updated**. Add telemetry on `schema=` call counts to know when removal is safe — the alias should not be removed while any caller is still using it.

---

## Workstream C — Error model

### Current problems (from audit, 2026-05-05)

- Errors sometimes appear in the MCP error field and sometimes in the success output string. The agent has no consistent way to detect failure.
- Error text leaks internal SQL (e.g., `DESCRIBE "..."` appears in `get_semantics` bad-schema errors).
- No machine-readable error code, no recovery hint — the agent has to pattern-match on free-form English.
- Trino syntax error response dumps ~250 tokens of keyword list, which is noise for the agent and bloats context.

### Required end state for every error

All errors must:

1. **Surface in the MCP error response field** (not the success output).
2. **Include this JSON shape:**
   ```json
   {
     "code": "MOSAIC_PROJECT_NOT_FOUND",
     "message": "Project 'nonexistent_project_xyz' does not exist or is not accessible to this user.",
     "recovery_hint": "Call get_projects to list available projects, then retry with a valid project name.",
     "details": { "project": "nonexistent_project_xyz", "request_id": "<uuid>" }
   }
   ```
3. **Never include internal SQL or the raw Trino keyword dump** in `message` or `details`. These belong in server logs only, tagged with `request_id`.

### Complete error taxonomy (implement all 11 codes)

| Code | Trigger | Recovery hint |
|---|---|---|
| `MOSAIC_AUTH_INVALID` | Missing / expired / insufficient-scope token | Re-authenticate. If using a PAT, regenerate it in the Strategy admin UI. |
| `MOSAIC_PROJECT_NOT_FOUND` | `project` arg doesn't match any accessible project | Call `get_projects` to list available projects, then retry with a valid name. |
| `MOSAIC_MODEL_NOT_FOUND` | `model` arg doesn't exist in the given project | Call `get_mosaic_models(project=...)` to list models in that project. |
| `MOSAIC_SEMANTICS_UNAVAILABLE` | Server reached but cube info / metadata fetch failed (Bug #2 case) | Retry once. If it persists, the model's metadata may be in an inconsistent state — surface the model name to the user and suggest they check the model in the Strategy UI. Do not retry more than 2x. |
| `MOSAIC_SQL_SYNTAX` | Trino parse error | Inspect `details.parser_message`. The query is malformed; rewrite and retry. (Do NOT include the Trino keyword dump in the recovery hint.) |
| `MOSAIC_SQL_TABLE_NOT_FOUND` | Table referenced in SQL doesn't exist in the schema | Call `get_mosaic_models(project=...)` to list tables. Model names with spaces must be double-quoted. |
| `MOSAIC_SQL_COLUMN_NOT_FOUND` | Column referenced in SQL doesn't exist | Call `get_semantics(project=..., model=...)` to re-read columns. Remember the `<form>__<name>` convention. |
| `MOSAIC_SQL_WRITE_REJECTED` | Statement is INSERT/UPDATE/DELETE/MERGE/CREATE/DROP/etc. | This connector is read-only. Rewrite as SELECT or ask the user to use the Strategy UI for writes. |
| `MOSAIC_QUERY_TIMEOUT` | SQL exceeded server-side timeout | Add a `LIMIT`, narrow the time range, or replace ad-hoc aggregation with a pre-defined metric from `get_semantics`. |
| `MOSAIC_RATE_LIMITED` | Per-user / per-token QPS exceeded | Wait `details.retry_after_seconds` and retry. |
| `MOSAIC_INTERNAL` | Anything not classified above | Retry once. If it persists, this is a server-side issue; the agent should report it to the user rather than retry indefinitely. |

### Code-change locations on the server

1. **MCP server response layer:** route all failures to the MCP error response field. Never return errors in the success output.
2. **MCP server response layer:** wrap raw backend errors with the taxonomy above using a pattern-matching wrapper.
3. **MCP server response layer:** strip `DESCRIBE "..."` and Trino keyword dumps from `message`/`details`. Tag each error with `request_id` so the support flow can correlate to logs.
4. **MCP server `query` tool:** add the pre-execution AST check (Workstream A, item A4).
5. **MCP server:** add per-token rate limiter to enable `MOSAIC_RATE_LIMITED` — required for marketplace listing.

---

## Bug tracker (open items)

| Bug | Repro | Current behavior | Expected behavior after fix |
|---|---|---|---|
| **Bug #1** | `query(schema="nonexistent_schema", query="SELECT 1")` | Succeeds, returns `1` despite the bad schema scope. | `MOSAIC_PROJECT_NOT_FOUND` (after Workstream C). |
| **Bug #2** | `get_semantics(project="platform analytics", model="logisticsoperationsdatabase")` | `Strategy Metadata Error: Failed to get all cube infos`. | Either succeeds (if the underlying metadata issue is resolved) or returns `MOSAIC_SEMANTICS_UNAVAILABLE` with a clean message. |

Both bugs have regression tests in this repo:
- Bug #1 → `tests/python/test_mcp_integration.py::test_schema_arg_ignored_for_tableless_query` (currently asserts the buggy behavior; flip when fixed).
- Bug #2 → `tests/python/test_mcp_integration.py::test_get_semantics_unavailable_model` (currently `xfail`; remove marker when fixed).

---

## Integration test checklist (for eng to verify after each workstream)

### After Workstream B lands

- [ ] `get_projects()` returns project list with no duplicated header
- [ ] `get_mosaic_models(project="world demos")` returns models only (no project list duplication)
- [ ] `get_mosaic_models(schema="world demos")` still works, emits a deprecation log
- [ ] `get_semantics(project=..., model=...)` response includes `__` legend at top
- [ ] `initialize` response includes the server-level `instructions` field

### After Workstream C lands

- [ ] Syntax error → MCP error field, code `MOSAIC_SQL_SYNTAX`, no keyword dump
- [ ] Invalid project → MCP error field, code `MOSAIC_PROJECT_NOT_FOUND`
- [ ] `INSERT` statement → MCP error field, code `MOSAIC_SQL_WRITE_REJECTED`
- [ ] No auth → MCP error field, code `MOSAIC_AUTH_INVALID`
- [ ] Every error response carries a `request_id` in `details`

### After Workstream A lands

- [ ] Non-Cowork Claude Agent SDK install → redirect works end-to-end
- [ ] Token expiry → `MOSAIC_AUTH_INVALID` with reconnect message
- [ ] `environment_url` config field routes to the correct Strategy environment
