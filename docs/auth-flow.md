# Mosaic plugin — auth flow

> Audience: Anthropic plugin marketplace reviewers. This doc walks the auth
> mechanism end-to-end and lists what to test before publishing.

## 1. Auth mechanism — named-user OAuth 2.0 redirect

When a user installs the Mosaic plugin and calls any Mosaic tool for the first
time, the MCP server returns a **redirect URL** pointing to the user's Strategy
environment login page:

```
https://<environment_url>/login?redirect=<mcp-callback>&state=<csrf>
```

The Claude Agent SDK opens this URL in the user's browser, the user
authenticates against Strategy (SSO / SAML / username+password — whatever the
customer has configured), and on success the MCP server issues a **30-day
access token**. The SDK stores the token in its credential store and includes
it on every subsequent tool call as a bearer header.

The user does not see the token. They never type a password into Claude. The
only credentials Claude touches are the opaque token returned by the redirect.

## 2. Token scope — bound to the authenticated Strategy user

The token is bound to the user who completed the login. Every tool call the
plugin makes inherits **that user's existing Strategy permissions**:

- Project access (which projects they can `get_projects` see)
- Model visibility within a project
- Row-level security (RLS) and column-level security (CLS) on every `query`

The agent **cannot** see data the user is not permitted to see. A Mosaic admin
who restricts a user to one project sees the same restriction reflected in the
agent's behavior — no escalation, no impersonation.

## 3. Token expiry — surfaces as `MOSAIC_AUTH_INVALID`

At day 31, the next tool call returns the MCP error code
`MOSAIC_AUTH_INVALID`. The skill instructs the agent to surface this to the
user in plain English:

> "Your Mosaic session has expired. Please reconnect via the plugin settings."

The user re-authenticates via the same redirect flow. There is no silent
refresh and no mid-session redirect — expiry is visible to the user.

## 4. Multi-environment — `environment_url` plugin config

Users with multiple Strategy environments (dev / staging / prod) specify their
`environment_url` in the plugin config at install time. This field is declared
in `plugin.json` under `config_schema` and is **required** for installation.

The `environment_url` determines:

- The redirect target on first connect
- The audience claim on the issued token
- The MCP server endpoint the plugin talks to

A user can install the plugin multiple times against different environments
(by giving each install a different config) and the SDK will keep the tokens
isolated.

## 5. Read-only enforcement

The `query` tool **rejects any statement whose root is not** `SELECT`,
`WITH`, `EXPLAIN`, `SHOW`, or `DESCRIBE`. Rejected statements return
`MOSAIC_SQL_WRITE_REJECTED`. This is enforced at the AST level on the server,
before the query reaches the backing data source.

Two layers of defense protect against accidental writes:

1. **AST check** on the MCP server (described above) — the tool shape itself
   is read-only.
2. **Named-user RBAC** on the backing data source — even if the AST check
   were bypassed, the user's own data-source permissions would block writes
   from a read-only role.

## 6. What marketplace reviewers should test

| # | Scenario | Expected behavior |
|---|---|---|
| 1 | Install plugin → first tool call | Browser opens to `https://<environment_url>/login`. After login, the tool call completes and returns a real result. |
| 2 | Subsequent tool calls within the 30-day window | Succeed silently with no further user interaction. |
| 3 | Simulate expired token (or wait 31 days) | Next tool call returns `MOSAIC_AUTH_INVALID`. The agent surfaces "Your Mosaic session has expired. Please reconnect via the plugin settings." |
| 4 | `INSERT INTO foo VALUES (1)` via the `query` tool | Returns `MOSAIC_SQL_WRITE_REJECTED`. No write is attempted on the backing data source. |
| 5 | A user with restricted project access | `get_projects` returns only projects the user can see. Attempting to query a hidden project returns `MOSAIC_PROJECT_NOT_FOUND`. |
| 6 | `environment_url` config | Pointing two installs at different environment URLs keeps tokens, project lists, and query results isolated. |

For test environments and credentials, contact the Strategy team.
