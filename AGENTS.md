# LumiBot Agent Instructions (Theta / Downloader Focus)

These rules are mandatory whenever you work on ThetaData integrations.

## Multi-Agent Collaboration (CRITICAL)
This repo is frequently edited by **multiple AI sessions**. To avoid lost work:

- **Branch etiquette:** if a task mandates a specific version branch (e.g., `4.4.25`), treat it as the shared branch—stay on it and do not create new branches/PRs unless explicitly instructed. Otherwise, start new work branches from a stable base branch (e.g., `dev`/`main`/`master`) and avoid chaining feature/WIP branches.
- **No “feature branch chaining”:** if you’re already on a feature/WIP or version branch (e.g., `feature/*`, `fix/*`, `wip/*`, `version/*`, `release/*`, or a version-named branch like `X.Y.Z`), keep working there; don’t create another feature branch from it unless explicitly instructed.
- **Branch naming (LumiBot convention):** prefer version-scoped branches so multiple agents can collaborate without “feature branch naming drift”. Use the repo’s existing convention (e.g., `4.4.25` or `version/X.Y.Z`).
  - Default for active release work: the shared version branch (e.g., `4.4.25`).
  - Avoid `feature/*` and `fix/*` here unless explicitly requested.
  - If you truly need isolation and are explicitly instructed to branch, use a scoped suffix (e.g., `4.4.25/<topic>` or `version/X.Y.Z/<topic>`)—but don’t chain off that unless explicitly instructed.
- **Never run `git checkout`.** Avoid other destructive operations (`git reset --hard`, `git clean -f`, `git stash`).
- **Dirty-tree safety:** if you need to branch with uncommitted changes, create the new branch from the current working tree so the changes come with you; avoid `git stash`. Verify with `git status --porcelain=v1`.
- **Before committing:** `git status` must be clean/understood; read diffs for any changes you didn’t personally create.
- **Avoid stepping on the CI agent:** if `tests/backtest/`, baselines, or CI workflows are in-flight, coordinate via `docs/handoffs/` and keep edits non-overlapping.
- **Document + test behavioral changes:** update the relevant docs in `docs/` and add regression tests in the same commit; add comments explaining “why/invariants” for non-obvious logic.
- **Cache safety:** never delete shared caches. Use S3 namespace versioning (e.g., `LUMIBOT_CACHE_S3_VERSION=...`) for cold-cache simulations; only delete cache objects when explicitly requested and tightly scoped (symbol/version-specific).

1. **Never launch ThetaTerminal locally WITH PRODUCTION CREDENTIALS.** Production has the only licensed session for that account. Starting the jar with prod credentials (even briefly or via Docker) instantly terminates the prod connection and halts all customers.
2. **Use the shared downloader endpoint for backtests.** All tests/backtests must set `DATADOWNLOADER_BASE_URL=http://data-downloader.lumiwealth.com:8080` and `DATADOWNLOADER_API_KEY=<secret>`. Do not short-cut by hitting Theta directly (and avoid hard-coded IPs—they can change on redeploy).

### Dev Credentials for Local ThetaTerminal Testing (SAFE)

There is a **separate dev account** that CAN be used for local debugging without affecting production:

| Field | Value |
|-------|-------|
| Username | `rob-dev@lumiwealth.com` |
| Password | `TestTestTest` |
| Bundle | STOCK.PRO, OPTION.PRO, INDEX.PRO |
| Location | `Strategy Library/Demos/.env` (commented out) |

**Verified working:** Dec 7, 2025

```bash
# Quick test with dev credentials
mkdir -p "/Users/robertgrzesik/Documents/Development/tmp/theta-dev-test"
echo -e "rob-dev@lumiwealth.com\nTestTestTest" > "/Users/robertgrzesik/Documents/Development/tmp/theta-dev-test/creds.txt"
java -jar $(python -c "import lumibot; import os; print(os.path.join(os.path.dirname(lumibot.__file__), 'tools', 'ThetaTerminal.jar'))") "/Users/robertgrzesik/Documents/Development/tmp/theta-dev-test/creds.txt" &
sleep 10
curl "http://127.0.0.1:25510/v2/status"  # Should show CONNECTED
pkill -f "ThetaTerminal.jar"  # Clean up
rm -rf "/Users/robertgrzesik/Documents/Development/tmp/theta-dev-test"
```

**Use dev credentials ONLY for:** Debugging ThetaTerminal itself, testing API endpoints, investigating data issues.
**Do NOT use for:** Running backtests (always use prod Data Downloader for consistent results).
3. **Respect the queue/backoff contract.** LumiBot no longer enforces a 30 s client timeout; instead it listens for the downloader’s `{"error":"queue_full"}` responses and retries with exponential backoff. If you add new downloader
   integrations, reuse that helper so we never DDoS the server.
4. **Long commands = safe-timeout (20m default max).** Wrap backtests/pytest/stress jobs with `/Users/robertgrzesik/bin/safe-timeout 1200s …` and break work into smaller chunks if it would run longer. Only use longer timeouts when absolutely necessary (e.g., explicit full-window acceptance backtests).
5. **Artifacts.** When demonstrating fixes, capture `Strategy\ Library/logs/*.log`, tear sheets, and downloader stress JSONs so the accuracy/dividend/resilience story stays reproducible.
6. **Write Location Policy (no “code files” outside Development).** Do not create helper scripts (e.g., `*.py`) under `/tmp` or other non-Development locations. Put LumiBot helpers under `scripts/` in this repo.

Failure to follow these rules will break everyone's workflows—double-check env vars before running anything.

---

## AGENTS.md / CLAUDE.md Best Practices (how we keep instructions useful)
- These instruction files are loaded automatically at session start. Keep guidance here **universal** and put deep, task-specific material in `docs/`.
- Prefer **progressive disclosure**:
  - Architecture + runbooks: `docs/` (start with `docs/BACKTESTING_ARCHITECTURE.md`).
  - Investigations and full trade audits: `docs/investigations/`.
  - Cross-session coordination: `docs/handoffs/`.
  - One-off helpers: `scripts/` (and keep them safe-timeout friendly).
  - **Public docs (Sphinx):** `docsrc/` is the source for the public documentation site; keep docstrings and Sphinx pages up to date for user-facing behaviors.
- When a workflow changes (new env vars, new cache semantics, new harness flags), update the relevant `docs/*` page in the same change set so other agents don’t re-learn it.
- **AI Navigation:** See `llms.txt` in repo root for structured documentation index
- **File naming convention (MANDATORY):** All docs use **UPPERCASE** names with underscores:
  - Root docs: `TOPIC_NAME.md` (e.g., `BACKTESTING_ARCHITECTURE.md`)
  - Handoffs: `YYYY-MM-DD_TOPIC_NAME.md` (e.g., `2026-01-04_THETADATA_HANDOFF.md`)
  - Investigations: `YYYY-MM-DD_TOPIC_NAME.md` (e.g., `2026-01-02_ACCURACY_AUDIT.md`)
  - Date-first for chronological sorting; UPPERCASE for consistency
- **File header (REQUIRED):** New docs must start with: Title, one-line description, Last Updated date, Status, Audience, and Overview section
- Interop note: `AGENTS.md` is the cross-tool convention; `CLAUDE.md` is Claude Code’s native file. If you want a single source of truth, Claude Code supports importing:
  - `@AGENTS.md`

## Env var documentation (REQUIRED)
- **Do not add new environment variables by default.** Env vars are hard to discover, hard to document, and easy to
  drift across deploy targets. Prefer explicit function parameters, config objects, or stable defaults.
- Only introduce a new env var when it is genuinely required for deployment/runtime configuration (secrets, endpoints,
  toggles needed for ops/rollout), and keep it narrowly scoped.
- If you add or change an environment variable, update:
  - `docsrc/environment_variables.rst` (public docs), and
  - `docs/ENV_VARS.md` when engineering notes help contributors.

## Changelog Maintenance (MANDATORY)

**Location:** `CHANGELOG.md`

**CRITICAL:** The changelog MUST be updated for every deployment, release, or significant change.

### When to Update

- **Deployments** - Any code deployed to production
- **Version bumps** - New version tags or releases
- **Bug fixes** - Data source, split, dividend, or broker fixes
- **New features** - New brokers, data sources, strategy capabilities
- **Breaking changes** - API changes, env var changes (mark with ⚠️)
- **Performance/dependency updates**

### Format

```markdown
## X.Y.Z - YYYY-MM-DD

### Added
- New feature

### Changed
- Modified behavior

### Fixed
- Bug fix

### Deprecated / Removed / Security
- As applicable
```

### Pre-Deployment Checklist

- [ ] Changelog entry added with current date
- [ ] Version number updated (if applicable)
- [ ] All significant changes documented
- [ ] Breaking changes marked with ⚠️

**If changelog wasn't updated, add a retroactive entry before the next deployment.**

### GitHub Release Markers (RECOMMENDED)

To keep deployments traceable (and easy to diff):

- **Tag the deploy commit** with the semantic version (annotated tag): `vX.Y.Z`
- **Push the tag** to GitHub
- **Create a GitHub Release** from that tag and paste the corresponding `CHANGELOG.md` entry
- **PR title convention:** `X.Y.Z` (or `Release X.Y.Z`) so the version is visible in the PR list

## Scoped instruction files
- `tests/AGENTS.md` — rules for everything under `tests/` (legacy-test authority policy).

## Documentation Layout

- `docs/` = hand-authored markdown (architecture, investigations, handoffs, ops notes); start with `docs/BACKTESTING_ARCHITECTURE.md`
- Handoffs: `docs/handoffs/`
- Investigations: `docs/investigations/`
- `docsrc/` = Sphinx source for the public docs site
- `generated-docs/` = local build output from `docsrc/` (gitignored)
- Docs publishing should happen via GitHub Actions on `dev` (avoid committing generated HTML)

---

## Test Philosophy (CRITICAL FOR ALL PROJECTS)

### Test Age = Test Authority

When tests fail, how you fix them depends on **how old the test is**:

| Test Age | Authority Level | How to Fix |
|----------|----------------|------------|
| **>1 year old** | LEGACY - High authority | **Fix the CODE**, not the test. These tests have proven themselves over time. |
| **6-12 months** | ESTABLISHED - Medium authority | Investigate carefully. Likely fix the code, but could be test issue. |
| **<6 months** | NEW - Lower authority | Test may need adjustment. Still verify code isn't broken. |
| **<1 month** | EXPERIMENTAL | Test is still being refined. Adjust as needed. |

### Check Test Age Before Fixing

```bash
git log --format="%ai" --follow -- tests/path/to/test.py | tail -1
```

### Conflict Resolution

When old tests and new tests conflict:
1. **Old test wins by default** - it has proven track record
2. If the new test represents genuinely new functionality, **ask the user for judgment**
3. Document any judgment calls in the test file with comments

This philosophy applies to ALL projects, not just LumiBot.
