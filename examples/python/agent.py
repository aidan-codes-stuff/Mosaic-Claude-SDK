"""
Mosaic Connect + Claude — minimal example agent (Python)

Demo questions to try once the agent is running:
    - "What projects do I have access to?"
    - "What are the top 10 customers by churn risk score in the customer health model?"
    - "Show me the available metrics in the world demos project."

Required env vars:
    MOSAIC_MCP_URL    — Mosaic MCP server endpoint
    ANTHROPIC_API_KEY — Anthropic API key

Run:
    pip install -r requirements.txt
    python agent.py
"""

import os
import sys

import anthropic
from dotenv import load_dotenv


SYSTEM_PROMPT = (
    "You are a data analyst with access to Mosaic, Strategy Software's "
    "governed semantic layer. Use the Mosaic tools to answer questions about "
    "business data. Always read a model's semantics before writing SQL. "
    "The connector is read-only."
)

MODEL = "claude-sonnet-4-6"


def main() -> int:
    load_dotenv()

    mcp_url = os.environ.get("MOSAIC_MCP_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not mcp_url:
        print("error: MOSAIC_MCP_URL is not set. See ../../.env.example.", file=sys.stderr)
        return 2
    if not api_key:
        print("error: ANTHROPIC_API_KEY is not set. See ../../.env.example.", file=sys.stderr)
        return 2

    client = anthropic.Anthropic(api_key=api_key)
    mcp_servers = [{"type": "url", "url": mcp_url, "name": "mosaic"}]
    history: list[dict] = []

    print("Mosaic agent ready. Ask a question, or Ctrl-D / Ctrl-C to exit.\n")

    while True:
        try:
            question = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue

        history.append({"role": "user", "content": question})

        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=history,
            mcp_servers=mcp_servers,
            betas=["mcp-client-2025-04-04"],
        )

        assistant_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        history.append({"role": "assistant", "content": response.content})

        print(f"\nclaude > {assistant_text.strip()}\n")


if __name__ == "__main__":
    raise SystemExit(main())
