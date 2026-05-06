# Mosaic Connect + Claude — TypeScript example

A minimal interactive agent that connects Claude to your Mosaic environment via the Mosaic Connect plugin (and the Mosaic MCP server it points at).

## Prerequisites

- Node.js 20+
- A Strategy account with access to at least one Mosaic project
- An Anthropic API key
- The Mosaic MCP server URL (provided by Strategy)

## Setup

```bash
cd examples/typescript
npm install
```

Create a `.env` file in the repo root (see `.env.example`):

```
MOSAIC_MCP_URL=https://<your-strategy-environment>/mcp
ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
npm start
```

You'll see a `you >` prompt. Try one of these:

- `What projects do I have access to?`
- `What are the top 10 customers by churn risk score in the customer health model?`
- `Show me the available metrics in the world demos project.`

The first tool call will redirect you to your Strategy login page. After login, a 30-day token is stored by the SDK and reused on every subsequent call. See [`docs/auth-flow.md`](../../docs/auth-flow.md) for details.

## How it works

The example uses the Anthropic TypeScript SDK's MCP connector (beta). The SDK forwards the `mcp_servers` list to the Anthropic API, which calls the Mosaic MCP server on your behalf and stitches the tool results back into the assistant response. The agent doesn't run a manual tool loop — it just reads stdin, sends a message, and prints the assistant text.

The model defaults to `claude-sonnet-4-6`. To change it, edit `MODEL` in `agent.ts`.

## Troubleshooting

- **"MOSAIC_MCP_URL is not set"** — Check that `.env` exists at the repo root and the var is spelled correctly.
- **"Your Mosaic session has expired"** — Tokens last 30 days. Reconnect via the plugin settings (or, for this example, just re-run; the redirect will fire again).
- **Empty / odd responses** — The agent depends on the skills under `skills/` to sequence calls. If you're seeing weird behavior, confirm your plugin install picked up both `skills/mosaic/SKILL.md` and `skills/mosaic-query-patterns/SKILL.md`.
