# Mosaic Connect Claude SDK plugin

**Mosaic Connect** is the Claude Agent SDK plugin that connects Claude agents to **Mosaic** — Strategy Software's governed semantic layer — so they can answer business-data questions against your Mosaic environment using read-only Trino SQL backed by validated metrics. You install Mosaic Connect; Mosaic itself is the backend it talks to.

## What this plugin does

Mosaic MCP runs inside your Strategy environment. Strategy provides documentation on how to enable the MCP server in your env and how to point a client at it; this repo is the client side. Mosaic Connect packages the Claude-side glue — a manifest (`plugin.json`), two skills under `skills/` that teach agents how to reason about Mosaic and how to write correct queries against the four tools (`get_projects` → `get_mosaic_models` → `get_semantics` → `query`), working example agents in Python and TypeScript, and an integration-test harness that hits the live server.

**Goal:** a third-party developer runs `claude plugin install mosaic-connect`, authenticates against their Strategy environment, and has an agent that can answer governed data questions within minutes.

## Prerequisites

- A Strategy account with access to at least one Mosaic project
- The Claude Agent SDK (`claude` CLI) — see [Anthropic's docs](https://docs.anthropic.com/claude/docs)
- An Anthropic API key (for the example agents)
- Python 3.10+ (for the Python example) or Node.js 20+ (for the TypeScript example)

## Installation

```bash
claude plugin install mosaic-connect
```

When prompted for `environment_url`, enter your Strategy environment URL (e.g. `https://your-company.strategy.com`). The first tool call will redirect you to that environment's login page; after login, a 30-day token is stored by the SDK and reused on every subsequent call. Full auth walkthrough: [`docs/auth-flow.md`](docs/auth-flow.md).

For local development (running the example agents directly), copy `.env.example` to `.env` and fill in:

```
MOSAIC_MCP_URL=https://<your-strategy-environment>/mcp
ANTHROPIC_API_KEY=sk-ant-...
```

## Quick start

- **Python:** [`examples/python/README.md`](examples/python/README.md)
- **TypeScript:** [`examples/typescript/README.md`](examples/typescript/README.md)

Both examples spin up an interactive REPL. Try:

- `What projects do I have access to?`
- `What are the top 10 customers by churn risk score in the customer health model?`
- `Show me the available metrics in the world demos project.`

## Running integration tests

The integration tests hit the live Mosaic MCP server (no mocks) and serve as the regression harness for documented bugs and current server behavior.

**Python:**

```bash
cd tests/python
pip install -r requirements-test.txt
pytest test_mcp_integration.py -v
```

**TypeScript:**

```bash
cd tests/typescript
npm install
npx vitest run
```

Both test suites skip gracefully if `MOSAIC_MCP_URL`, `MOSAIC_TEST_PROJECT`, and `MOSAIC_TEST_MODEL` are not set — CI without credentials will not fail noisily. Two tests are intentionally marked as expected failures: they document open bugs being tracked in [`docs/server-changes-plan.md`](docs/server-changes-plan.md).

## How the auth flow works

Named-user OAuth 2.0 redirect, 30-day token, multi-environment via the `environment_url` config field. Full walkthrough including what marketplace reviewers should test: [`docs/auth-flow.md`](docs/auth-flow.md).

## Server-side change plan

Three workstreams of changes are needed on the live MCP server before this plugin can be listed on the Anthropic plugin marketplace (tool-schema rewrites, error-model standardization, and auth verification). They're tracked in [`docs/server-changes-plan.md`](docs/server-changes-plan.md). This repo ships independently of those changes; the integration tests document current behavior and contain `NOTE:` markers showing what to update when each workstream lands.

## Reporting bugs / contributing

Please file issues at [github.com/aidan-codes-stuff/Mosaic-Claude-SDK/issues](https://github.com/aidan-codes-stuff/Mosaic-Claude-SDK/issues). Include:

- Plugin version (`plugin.json`)
- Strategy environment URL (or "redacted")
- The full tool call sequence the agent attempted
- Server response (with `request_id` if available)
