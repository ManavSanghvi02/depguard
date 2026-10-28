# ADR-0011: MCP mounted in the API, with per-user API tokens
- Status: Accepted
- Date: 2026-10-28

## Context
The secondary user asks an AI assistant "am I affected by CVE-X?". DepGuard exposes three **read-only** MCP
tools: `list_top_risks`, `am_i_affected`, `explain_finding`. MCP answers must equal the web API's answers
(parity metric), and one user must never see another user's data.

## Options

**Option A: mount the MCP server inside the FastAPI app at `/mcp`; authenticate with per-user API tokens**
- One deploy; MCP tools call the **same service functions** as the REST routes, so parity holds by design.
- Simple tokens that users create and revoke in the web app.
- MCP shares the API's public address and cold start, so it **must** be strictly authenticated.

**Option B: a separate MCP service with OAuth login**
- Isolated from the main API; OAuth is MCP's standard sign-in flow.
- A second deploy on a free tier, and OAuth is a lot of work for the MVP.

## Decision
**Option A.**
- **Every** `/mcp` request needs `Authorization: Bearer <token>`; missing or invalid → `401`.
- Tokens are long and random, **shown once**, stored only as a **SHA-256 hash** plus a short prefix for display,
  revocable, with `last_used_at` tracked.
- **Each tool works out the user from the token** and queries only that user's repos, services and findings. No
  tool accepts a `user_id` argument.
- No tool can change anything (no PRs, no scans).
- Tests prove that user A's token can never read user B's data, through MCP or REST.

## Trade-offs
- **Gain:** one deploy, parity by design, simple auth.
- **Give up:** MCP shares the API's attack surface and cold start; per-user tokens are less polished than OAuth.
- **Revisit if:** MCP clients broadly expect OAuth, or MCP traffic needs to scale separately.
