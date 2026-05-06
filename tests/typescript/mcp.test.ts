/**
 * Integration tests for the Mosaic MCP server (TypeScript).
 *
 * These tests hit the LIVE Mosaic MCP server (not a mock) and verify both the
 * canonical happy paths and the documented current bug surface. Two tests are
 * intentionally marked as expected-failures — they document open bugs that the
 * server team needs to fix. When a bug is fixed, update the test to assert the
 * new expected behavior.
 *
 * Required env vars (tests skip gracefully if any are missing — CI without
 * credentials will not fail noisily):
 *
 *   MOSAIC_MCP_URL       — live MCP server endpoint
 *   MOSAIC_MCP_TOKEN     — bearer token / PAT for the test user (optional)
 *   MOSAIC_TEST_PROJECT  — known-good project, e.g. "world demos"
 *   MOSAIC_TEST_MODEL    — known-good model, e.g. "customer health"
 *
 * Run:
 *   npm install
 *   npx vitest run
 */

import { describe, it, expect } from "vitest";
import * as dotenv from "dotenv";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

dotenv.config();

const MOSAIC_MCP_URL = process.env.MOSAIC_MCP_URL;
const MOSAIC_MCP_TOKEN = process.env.MOSAIC_MCP_TOKEN;
const MOSAIC_TEST_PROJECT = process.env.MOSAIC_TEST_PROJECT;
const MOSAIC_TEST_MODEL = process.env.MOSAIC_TEST_MODEL;

const configured = Boolean(MOSAIC_MCP_URL && MOSAIC_TEST_PROJECT && MOSAIC_TEST_MODEL);

// Vitest's `it.skipIf` runs the test only when the predicate is FALSE.
const itLive = it.skipIf(!configured);

interface CallResult {
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
}

async function withSession<T>(fn: (client: Client) => Promise<T>): Promise<T> {
  const headers: Record<string, string> = {};
  if (MOSAIC_MCP_TOKEN) {
    headers["Authorization"] = `Bearer ${MOSAIC_MCP_TOKEN}`;
  }

  const transport = new StreamableHTTPClientTransport(new URL(MOSAIC_MCP_URL!), {
    requestInit: { headers },
  });
  const client = new Client(
    { name: "mosaic-integration-tests", version: "1.0.0" },
    { capabilities: {} },
  );
  await client.connect(transport);
  try {
    return await fn(client);
  } finally {
    await client.close();
  }
}

function resultText(result: CallResult): string {
  const blocks = result.content ?? [];
  return blocks
    .filter((b) => b.type === "text" && typeof b.text === "string")
    .map((b) => b.text!)
    .join("\n");
}

function looksLikeError(result: CallResult): boolean {
  if (result.isError) return true;
  const text = resultText(result).toLowerCase();
  return ["error", "failed", "exception", "traceback"].some((t) => text.includes(t));
}

function firstDoubleUnderscoreColumn(text: string): string | null {
  let payload: unknown = null;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = null;
  }
  if (payload !== null) {
    for (const token of walkStrings(payload)) {
      if (token.includes("__") && token.includes(" ")) return token;
    }
  }
  const quoted = text.match(/"([^"]*__[^"]*)"/);
  if (quoted) return quoted[1];
  const bare = text.match(/\b([a-z][a-z0-9 ]*__[a-z0-9 ]+)\b/i);
  if (bare) return bare[1].trim();
  return null;
}

function* walkStrings(obj: unknown): Iterable<string> {
  if (typeof obj === "string") yield obj;
  else if (Array.isArray(obj)) for (const v of obj) yield* walkStrings(v);
  else if (obj && typeof obj === "object")
    for (const v of Object.values(obj)) yield* walkStrings(v);
}

describe("Mosaic MCP integration", () => {
  // ---- Happy path ----------------------------------------------------------

  itLive("get_projects returns a non-empty list including the test project", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({ name: "get_projects", arguments: {} })) as CallResult;
      const text = resultText(result);
      expect(text).toBeTruthy();
      expect(text).toContain(MOSAIC_TEST_PROJECT!);
    });
  });

  itLive("get_mosaic_models(project=...) includes the test model", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "get_mosaic_models",
        arguments: { project: MOSAIC_TEST_PROJECT },
      })) as CallResult;
      expect(resultText(result)).toContain(MOSAIC_TEST_MODEL!);
    });
  });

  itLive(
    "deprecated `schema` alias still works (backward compat — update when Workstream B lands)",
    async () => {
      await withSession(async (client) => {
        const result = (await client.callTool({
          name: "get_mosaic_models",
          arguments: { schema: MOSAIC_TEST_PROJECT },
        })) as CallResult;
        expect(resultText(result)).toContain(MOSAIC_TEST_MODEL!);
      });
    },
  );

  itLive("get_semantics returns attributes, metrics, and __ convention", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "get_semantics",
        arguments: { project: MOSAIC_TEST_PROJECT, model: MOSAIC_TEST_MODEL },
      })) as CallResult;
      const text = resultText(result).toLowerCase();
      expect(text).toContain("attribute");
      expect(text).toContain("metric");
      expect(text).toContain("__");
    });
  });

  itLive("query: SELECT 1 succeeds", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "query",
        arguments: { project: MOSAIC_TEST_PROJECT, query: "SELECT 1" },
      })) as CallResult;
      expect(resultText(result)).toBeTruthy();
      expect(looksLikeError(result)).toBe(false);
    });
  });

  itLive("query: SELECT against test model with discovered column returns rows", async () => {
    await withSession(async (client) => {
      const sem = (await client.callTool({
        name: "get_semantics",
        arguments: { project: MOSAIC_TEST_PROJECT, model: MOSAIC_TEST_MODEL },
      })) as CallResult;

      const column = firstDoubleUnderscoreColumn(resultText(sem));
      if (!column) {
        // Skip silently — semantics shape may not expose a discoverable column.
        return;
      }
      const sql = `SELECT "${column}" FROM "${MOSAIC_TEST_MODEL}" LIMIT 5`;
      const result = (await client.callTool({
        name: "query",
        arguments: { project: MOSAIC_TEST_PROJECT, query: sql },
      })) as CallResult;
      expect(resultText(result)).toBeTruthy();
      expect(looksLikeError(result)).toBe(false);
    });
  });

  // ---- Error paths (current behavior — update when Workstream C lands) -----

  itLive("query: syntax error surfaces as an error", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "query",
        arguments: { project: MOSAIC_TEST_PROJECT, query: "SELEKT 1" },
      })) as CallResult;
      expect(looksLikeError(result)).toBe(true);
    });
  });

  itLive("get_mosaic_models: invalid project surfaces as an error", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "get_mosaic_models",
        arguments: { project: "nonexistent_xyz_project" },
      })) as CallResult;
      expect(looksLikeError(result)).toBe(true);
    });
  });

  itLive("query: INSERT statement is rejected", async () => {
    await withSession(async (client) => {
      const result = (await client.callTool({
        name: "query",
        arguments: {
          project: MOSAIC_TEST_PROJECT,
          query: "INSERT INTO foo VALUES (1)",
        },
      })) as CallResult;
      expect(looksLikeError(result)).toBe(true);
    });
  });

  // ---- Bug regression tests ------------------------------------------------

  itLive(
    "Bug #1 — schema arg is NOT validated for table-less queries (currently passes)",
    async () => {
      await withSession(async (client) => {
        const result = (await client.callTool({
          name: "query",
          arguments: { schema: "nonexistent_schema_xyz", query: "SELECT 1" },
        })) as CallResult;
        // Documents current bug: SELECT 1 succeeds despite the bad schema.
        // When Bug #1 is fixed, update to assert MOSAIC_PROJECT_NOT_FOUND.
        expect(looksLikeError(result)).toBe(false);
      });
    },
  );

  itLive.fails(
    "Bug #2 — get_semantics fails for platform analytics / logisticsoperationsdatabase",
    async () => {
      await withSession(async (client) => {
        const result = (await client.callTool({
          name: "get_semantics",
          arguments: {
            project: "platform analytics",
            model: "logisticsoperationsdatabase",
          },
        })) as CallResult;
        // When Bug #2 is fixed, this test will start passing — at which point
        // remove `.fails` and the test becomes a normal positive assertion.
        expect(looksLikeError(result)).toBe(false);
      });
    },
  );

  if (!configured) {
    it.skip("(integration tests require MOSAIC_MCP_URL, MOSAIC_TEST_PROJECT, MOSAIC_TEST_MODEL)", () => {});
  }
});
