/**
 * Mosaic + Claude — minimal example agent (TypeScript)
 *
 * Demo questions to try once the agent is running:
 *   - "What projects do I have access to?"
 *   - "What are the top 10 customers by churn risk score in the customer health model?"
 *   - "Show me the available metrics in the world demos project."
 *
 * Required env vars:
 *   MOSAIC_MCP_URL    — Mosaic MCP server endpoint
 *   ANTHROPIC_API_KEY — Anthropic API key
 *
 * Run:
 *   npm install
 *   npm start
 */

import Anthropic from "@anthropic-ai/sdk";
import * as dotenv from "dotenv";
import * as readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

const SYSTEM_PROMPT =
  "You are a data analyst with access to Mosaic, Strategy Software's " +
  "governed semantic layer. Use the Mosaic tools to answer questions about " +
  "business data. Always read a model's semantics before writing SQL. " +
  "The connector is read-only.";

const MODEL = "claude-sonnet-4-6";

async function main(): Promise<number> {
  dotenv.config();

  const mcpUrl = process.env.MOSAIC_MCP_URL;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!mcpUrl) {
    console.error("error: MOSAIC_MCP_URL is not set. See ../../.env.example.");
    return 2;
  }
  if (!apiKey) {
    console.error("error: ANTHROPIC_API_KEY is not set. See ../../.env.example.");
    return 2;
  }

  const client = new Anthropic({ apiKey });
  const mcpServers = [{ type: "url" as const, url: mcpUrl, name: "mosaic" }];
  const history: Anthropic.Beta.BetaMessageParam[] = [];

  const rl = readline.createInterface({ input, output });
  console.log("Mosaic agent ready. Ask a question, or Ctrl-D / Ctrl-C to exit.\n");

  try {
    while (true) {
      const question = (await rl.question("you > ")).trim();
      if (!question) continue;

      history.push({ role: "user", content: question });

      const response = await client.beta.messages.create({
        model: MODEL,
        max_tokens: 4096,
        system: SYSTEM_PROMPT,
        messages: history,
        mcp_servers: mcpServers,
        betas: ["mcp-client-2025-04-04"],
      });

      const assistantText = response.content
        .filter((b): b is Anthropic.Beta.BetaTextBlock => b.type === "text")
        .map((b) => b.text)
        .join("");

      history.push({ role: "assistant", content: response.content });
      console.log(`\nclaude > ${assistantText.trim()}\n`);
    }
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === "ERR_USE_AFTER_CLOSE") return 0;
    throw err;
  } finally {
    rl.close();
  }
}

main().then((code) => process.exit(code ?? 0));
