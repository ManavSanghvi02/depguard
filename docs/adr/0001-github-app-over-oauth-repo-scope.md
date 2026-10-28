# ADR-0001: GitHub App with narrow permissions, not the OAuth `repo` scope
- Status: Accepted
- Date: 2026-10-28

## Context
Fix PRs (story 6) need permission to push a branch and open a pull request. Private-repo scanning (after the
MVP) will need read access to private code. Sign-in only needs to know *who* the user is.

## Options

**Option A: OAuth app with the `repo` (or `public_repo`) scope**
- Simple: the user's login token does everything.
- The token **acts as the user** across **every** repository they can access, with full read/write; it lives as
  long as the user's session. A leak would be a serious incident for the user.

**Option B: GitHub App**
- Its own identity, separate from the user.
- **Fine-grained permissions** (here: *Contents: write*, *Pull requests: write*, *Metadata: read*).
- Installed **only on repos the user picks**.
- Short-lived installation tokens (about an hour).
- More setup: an App registration and a private key.

## Decision
**Option B.** Sign-in uses Supabase's GitHub login for **identity only** (no repo scope). A GitHub App is used **only
for writing fix PRs** in the MVP. Private-repo reading will later be added to the same App (*Contents: read* on
private repos the user chooses). For repos where the App isn't installed, DepGuard shows a patch instead.

### Who may get a fix PR (added after review)
The App *being able* to write to a repo doesn't mean *the person asking* may use it. Anyone can add any public
repo by URL, so without a check a stranger could make DepGuard open PRs on someone else's repo. That is a
**confused deputy**: a trusted program misused by someone with less permission.

**Option 1: store installation data from GitHub's installation webhook.**
- Fast lookups.
- A webhook endpoint can be forged if its signature check is ever missing or wrong, and Render's free server is often
  asleep for longer than GitHub waits for a reply, so events would be lost.

**Option 2: check ownership live when a fix is requested.**
- Always current; no endpoint to attack; nothing to keep in sync.
- One or two extra GitHub API calls per fix request.

**Decision: Option 2.**
1. Render pre-checks that the repo's owner is a **personal account** whose **numeric GitHub user ID** equals the
   requester's.
2. The `publish` job, which holds the App key ([ADR-0010](0010-fix-prs-built-in-github-actions.md)), looks up the
   App installation for the repo and opens a PR **only if the installation's account has the same numeric ID**.
3. Otherwise DepGuard stores a patch.

Numeric IDs, not usernames, because usernames can be renamed and reused. **Personal repos only in the MVP**;
organization repos (members, roles) come later. **If webhooks are ever added, every delivery must be verified with
the `X-Hub-Signature-256` header.**

## Trade-offs
- **Gain:** least privilege; the user controls exactly which repos DepGuard can touch; tokens expire quickly.
- **Give up:** more setup work; a highly sensitive **App private key** to protect. That key lives **only** in the protected
  `fix-pr` GitHub Actions environment, not on Render ([ADR-0010](0010-fix-prs-built-in-github-actions.md),
  [security.md](../security.md)).
- **Revisit if:** GitHub's fine-grained OAuth options ever match an App's per-repo control.
