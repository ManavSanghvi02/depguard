# ADR-0012: Fetch only lockfiles via the tree API with a read-only token
- Status: Accepted
- Date: 2026-10-28

## Context
A scan needs only the lockfiles of a repo, which is a few files out of possibly thousands. Unauthenticated GitHub
API calls are limited to 60 per hour, too few for scanning. The MVP covers public repos only.

## Options

**Option A: clone the repo** (shallow clone)
- Simple; no API rate limits for file contents.
- Downloads far more than needed; uses disk and memory on Render's 512 MB; slower for large repos.

**Option B: tree API + blob API with DepGuard's own read-only token**
- `git/trees/{sha}?recursive=1` lists every path in one call; DepGuard then downloads only the matching lockfiles
  through the blob API, which also works for files over 1 MB.
- An authenticated token allows 5,000 requests per hour.
- Very large repos can return a **truncated** tree; one more secret to protect.

## Decision
**Option B.** If the tree is truncated, the scan is marked `partial` with that reason. The read token
grants read-only access to public repositories, lives only on Render, and is listed in [security.md](../security.md).

## Trade-offs
- **Gain:** a few small requests per scan; low memory; fast.
- **Give up:** truncated trees on huge repos (reported, never silent); a token to manage.
- **Revisit if:** truncation is common on real repos. Walking the tree folder by folder is then the fallback.
