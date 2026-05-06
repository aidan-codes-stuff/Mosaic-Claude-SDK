"""Integration tests for the Mosaic MCP server.

These tests hit the LIVE Mosaic MCP server (not a mock) and verify both the
canonical happy paths and the documented current bug surface. Two of the tests
are intentionally marked xfail — they document open bugs that the server team
needs to fix. When a bug is fixed, update the test (remove the xfail marker
and assert the new expected behavior).

Required env vars (tests skip gracefully if any are missing — CI without
credentials will not fail noisily):

    MOSAIC_MCP_URL       — live MCP server endpoint
    MOSAIC_MCP_TOKEN     — bearer token / PAT for the test user (optional;
                           omit if your endpoint embeds auth in the URL)
    MOSAIC_TEST_PROJECT  — known-good project, e.g. "world demos"
    MOSAIC_TEST_MODEL    — known-good model, e.g. "customer health"

Run:
    pip install -r requirements-test.txt
    pytest test_mcp_integration.py -v
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import pytest
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()

MOSAIC_MCP_URL = os.environ.get("MOSAIC_MCP_URL")
MOSAIC_MCP_TOKEN = os.environ.get("MOSAIC_MCP_TOKEN")
MOSAIC_TEST_PROJECT = os.environ.get("MOSAIC_TEST_PROJECT")
MOSAIC_TEST_MODEL = os.environ.get("MOSAIC_TEST_MODEL")

REQUIRED_ENV = {
    "MOSAIC_MCP_URL": MOSAIC_MCP_URL,
    "MOSAIC_TEST_PROJECT": MOSAIC_TEST_PROJECT,
    "MOSAIC_TEST_MODEL": MOSAIC_TEST_MODEL,
}

skip_if_unconfigured = pytest.mark.skipif(
    any(v is None for v in REQUIRED_ENV.values()),
    reason=(
        "Mosaic live-server env vars not set; skipping integration tests. "
        f"Missing: {[k for k, v in REQUIRED_ENV.items() if v is None]}"
    ),
)

pytestmark = [pytest.mark.asyncio, skip_if_unconfigured]


@asynccontextmanager
async def mosaic_session() -> AsyncIterator[ClientSession]:
    """Open an MCP client session against the live Mosaic server."""
    headers: dict[str, str] = {}
    if MOSAIC_MCP_TOKEN:
        headers["Authorization"] = f"Bearer {MOSAIC_MCP_TOKEN}"

    async with streamablehttp_client(MOSAIC_MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _result_text(result: Any) -> str:
    """Concatenate text blocks from a tools/call result for substring checks."""
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _looks_like_error(result: Any) -> bool:
    """The current server returns errors in the success output string. Once
    Workstream C lands this becomes `result.isError`."""
    if getattr(result, "isError", False):
        return True
    text = _result_text(result).lower()
    return any(token in text for token in ("error", "failed", "exception", "traceback"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_get_projects_returns_list() -> None:
    """get_projects returns a non-empty list including the test project."""
    async with mosaic_session() as session:
        result = await session.call_tool("get_projects", {})
        text = _result_text(result)
        assert text, "get_projects returned no text content"
        assert MOSAIC_TEST_PROJECT in text, (
            f"expected test project '{MOSAIC_TEST_PROJECT}' in get_projects output"
        )


async def test_get_mosaic_models_with_project() -> None:
    """get_mosaic_models(project=...) returns models including the test model."""
    async with mosaic_session() as session:
        result = await session.call_tool(
            "get_mosaic_models", {"project": MOSAIC_TEST_PROJECT}
        )
        text = _result_text(result)
        assert MOSAIC_TEST_MODEL in text, (
            f"expected test model '{MOSAIC_TEST_MODEL}' in get_mosaic_models output"
        )


async def test_get_mosaic_models_deprecated_schema_alias() -> None:
    """Deprecated `schema` alias still works for backward compatibility.

    NOTE: this test documents CURRENT behavior. When the server ships the
    schema → project rename (Workstream B), update this test to also assert
    that a deprecation warning is emitted in the response or via a header.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "get_mosaic_models", {"schema": MOSAIC_TEST_PROJECT}
        )
        text = _result_text(result)
        assert MOSAIC_TEST_MODEL in text, (
            "deprecated `schema` alias should still return models"
        )


async def test_get_semantics_returns_attributes_and_metrics() -> None:
    """get_semantics returns a payload that mentions both attributes and metrics
    and uses the `<form>__<name>` column convention."""
    async with mosaic_session() as session:
        result = await session.call_tool(
            "get_semantics",
            {"project": MOSAIC_TEST_PROJECT, "model": MOSAIC_TEST_MODEL},
        )
        text = _result_text(result).lower()
        assert "attribute" in text, "semantics payload should mention attributes"
        assert "metric" in text, "semantics payload should mention metrics"
        assert "__" in text, (
            "semantics payload should reference the <form>__<name> convention"
        )


async def test_query_select_one() -> None:
    """A trivial SELECT 1 against the test project succeeds."""
    async with mosaic_session() as session:
        result = await session.call_tool(
            "query", {"project": MOSAIC_TEST_PROJECT, "query": "SELECT 1"}
        )
        text = _result_text(result)
        assert text, "SELECT 1 returned no content"
        assert not _looks_like_error(result), f"SELECT 1 should succeed; got: {text[:200]}"


async def test_query_with_limit() -> None:
    """A SELECT against the test model with a real column name returns rows.

    We discover a column dynamically from get_semantics so the test is robust
    to environment-specific column naming.
    """
    async with mosaic_session() as session:
        sem = await session.call_tool(
            "get_semantics",
            {"project": MOSAIC_TEST_PROJECT, "model": MOSAIC_TEST_MODEL},
        )
        sem_text = _result_text(sem)

        # Pull the first quoted `<form>__<name>` column we can find.
        column = _first_double_underscore_column(sem_text)
        if column is None:
            pytest.skip("Could not discover a `<form>__<name>` column from semantics output")

        sql = f'SELECT "{column}" FROM "{MOSAIC_TEST_MODEL}" LIMIT 5'
        result = await session.call_tool(
            "query", {"project": MOSAIC_TEST_PROJECT, "query": sql}
        )
        text = _result_text(result)
        assert text, f"query returned no content for SQL: {sql}"
        assert not _looks_like_error(result), (
            f"query should succeed; SQL={sql!r}; got: {text[:200]}"
        )


# ---------------------------------------------------------------------------
# Error paths (current behavior — update when Workstream C lands)
# ---------------------------------------------------------------------------


async def test_query_syntax_error_returns_error() -> None:
    """A syntactically invalid query surfaces as an error.

    NOTE: today the error often appears in the success output string rather
    than the MCP error field. After Workstream C ships, update this test to
    assert `result.isError is True` AND the error code is MOSAIC_SQL_SYNTAX.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "query", {"project": MOSAIC_TEST_PROJECT, "query": "SELEKT 1"}
        )
        assert _looks_like_error(result), (
            "syntactically invalid query should surface as an error"
        )


async def test_query_invalid_project_returns_error() -> None:
    """An invalid project name surfaces as an error.

    NOTE: today the error may come back in the success output string. After
    Workstream C, assert `result.isError is True` AND the error code is
    MOSAIC_PROJECT_NOT_FOUND.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "get_mosaic_models", {"project": "nonexistent_xyz_project"}
        )
        assert _looks_like_error(result), (
            "nonexistent project should surface as an error"
        )


async def test_query_write_rejected() -> None:
    """A write statement (INSERT) is rejected.

    NOTE: post Workstream C, assert error code MOSAIC_SQL_WRITE_REJECTED.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "query",
            {"project": MOSAIC_TEST_PROJECT, "query": "INSERT INTO foo VALUES (1)"},
        )
        assert _looks_like_error(result), "INSERT should be rejected by the read-only connector"


# ---------------------------------------------------------------------------
# Bug regression tests
# ---------------------------------------------------------------------------


async def test_schema_arg_ignored_for_tableless_query() -> None:
    """Bug #1 — schema arg is not validated for table-less queries.

    `query(schema="nonexistent_schema_xyz", query="SELECT 1")` currently
    succeeds despite the bad schema. This test documents the current buggy
    behavior. When Bug #1 is fixed, update this test to assert
    MOSAIC_PROJECT_NOT_FOUND is returned and remove the documenting comment.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "query",
            {"schema": "nonexistent_schema_xyz", "query": "SELECT 1"},
        )
        text = _result_text(result)
        # Currently passes: SELECT 1 succeeds despite the bad schema scope.
        assert not _looks_like_error(result), (
            f"Bug #1 documented behavior: SELECT 1 with bad schema currently "
            f"succeeds. If this fails, the bug may have been fixed — update "
            f"the test to assert MOSAIC_PROJECT_NOT_FOUND. Got: {text[:200]}"
        )


@pytest.mark.xfail(reason="Bug #2: get_semantics returns 'Failed to get all cube infos' for this model")
async def test_get_semantics_unavailable_model() -> None:
    """Bug #2 — get_semantics fails on a valid project/model pair with
    'Failed to get all cube infos'. Marked xfail so CI surfaces the open bug
    without breaking the build. Remove the xfail marker once Bug #2 is fixed.
    """
    async with mosaic_session() as session:
        result = await session.call_tool(
            "get_semantics",
            {"project": "platform analytics", "model": "logisticsoperationsdatabase"},
        )
        text = _result_text(result)
        assert not _looks_like_error(result), (
            f"Bug #2: metadata unavailable for this model. Got: {text[:200]}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_double_underscore_column(semantics_text: str) -> str | None:
    """Find the first `<form>__<name>` column reference in a semantics blob.

    Falls back to scanning JSON-quoted strings if the payload is JSON.
    """
    import re

    # Try JSON first
    try:
        payload = json.loads(semantics_text)
    except (ValueError, TypeError):
        payload = None

    if payload is not None:
        for token in _walk_strings(payload):
            if "__" in token and " " in token:
                return token

    # Fall back to regex over the raw text
    match = re.search(r'"([^"]*__[^"]*)"', semantics_text)
    if match:
        return match.group(1)
    match = re.search(r"\b([a-z][a-z0-9 ]*__[a-z0-9 ]+)\b", semantics_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _walk_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
