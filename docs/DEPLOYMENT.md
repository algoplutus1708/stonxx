# DEPLOYMENT

> Release/deployment workflow for LumiBot (version branches, changelog, tags, and GitHub releases).

**Last Updated:** 2026-01-27  
**Status:** Active  
**Audience:** Developers + AI Agents

---

## Goals

- Make deployments traceable (what code was deployed, when, and why).
- Keep multi-agent collaboration safe (shared `version/*` branches).
- Avoid “version drift” between deployed artifacts and `setup.py`.
- Make “what changed” readable (changelog + PR description quality).

---

## Branch + Version Rules (STRICT)

- Active work happens on a shared version branch: `version/X.Y.Z` (example: `version/4.4.31`).
- **Do not create extra branches** off a version branch unless explicitly instructed.
- **Do not bump** `setup.py` version just because work started.
  - Version bump happens at deployment time only.
- After a version branch is merged to `dev`, **immediately start the next version branch** (see Step 7).

---

## Release Captain Rules (STRICT)

When you are “the person deploying”, you own the release notes even if you didn’t write the code.

- **Read the full commit range** since the last `setup.py` bump and ensure `CHANGELOG.md` covers it.
- **Audit PRs** in the range for correctness, perf claims, and risk (don’t assume other bots did it right).
- **Enforce PR description quality** (template below).
- **Enforce perf evidence** when perf is claimed (YAPPI + measured before/after).

---

## PR Description Template (STRICT)

Every release PR should include:

- **What / Why:** one paragraph each.
- **Risk:** what could break; how to detect it quickly.
- **Tests run:** local commands + GitHub CI.
- **Perf evidence (if relevant):** exact commands + before/after numbers + profiler artifact path(s).
- **Docs:** links to investigation notes / runbooks if new operational behavior was added.

---

## Deployment Checklist (Recommended, end-to-end)

0) **Sync your local repo**
   - `git switch dev && git pull --ff-only`
   - `git switch version/X.Y.Z && git pull --ff-only`
   - Confirm clean tree: `git status --porcelain=v1` (must be empty)

1) **Verify tests**
   - Ensure required CI checks are green (unit + backtest + acceptance gates as applicable).
   - Local quick check (matches release workflow selection):
     - `python3 -m pytest -m "not apitest and not downloader" --tb=short -q --durations=30`

2) **Update changelog (FULL RANGE, not just “recent work”)**
   - Add/refresh the `CHANGELOG.md` entry for `X.Y.Z` (dated) and ensure it includes:
     - user-visible behavior changes
     - major perf changes (include before/after numbers)
     - operational changes (caches, infra dependencies, env vars, runbooks)
   - Include: `Deploy marker: <commit>` referencing the `deploy X.Y.Z` commit hash (added in Step 3).
   - The entry must include **all significant commits** since the previous `setup.py` version bump:
     - Find the previous bump commit:
       - `git log -p -- setup.py`
     - Build the draft changelog from the full range (pre-deploy marker):
       - `git log --oneline <previous-bump-commit>..HEAD`
     - After Step 3 creates the deploy-marker commit, re-run the range using that commit:
       - `git log --oneline <previous-bump-commit>..<deploy-marker-commit>`
   - If you merged before the changelog is complete, fix it immediately as a follow-up PR to `dev`.

3) **Bump version (deploy-marker commit)**
   - Update `setup.py` `version="X.Y.Z"`.
   - Commit with message: `deploy X.Y.Z` (this is the deploy marker).
   - This is the commit the release tag should point at.

4) **Tag + publish (preferred path)**
   - Create an annotated tag `vX.Y.Z` pointing at the deploy-marker commit.
   - Push the tag to GitHub.
   - Let `.github/workflows/release.yml` run:
     - validates tag ↔ `setup.py` ↔ `CHANGELOG.md`,
     - runs `pytest -m "not apitest and not downloader"`,
     - builds + publishes to PyPI,
     - creates the GitHub Release.

5) **Verify published artifacts**
   - PyPI is sometimes eventually-consistent (CDN/cache); the publish job can succeed but installs may fail for a few
     minutes. Always wait for the version to be visible/instalable before proceeding with downstream rollouts.
   - Confirm PyPI shows the expected version:
     - `python3 -m pip index versions lumibot | head`
   - Confirm the version is actually installable (retry for a few minutes):
     - `python3 -m pip install --no-deps "lumibot==X.Y.Z"`
     - If it fails, retry with a short loop:

       ```bash
       VERSION="X.Y.Z"
       for i in {1..20}; do
         if python3 -m pip install --no-deps "lumibot==${VERSION}"; then
           echo "OK: lumibot==${VERSION} is installable"
           break
         fi
         echo "Waiting for PyPI propagation (${i}/20)..."
         sleep 15
       done
       ```
   - If you want to “force” a fresh fetch in an environment that may have cached wheels:
     - `python3 -m pip install --upgrade --force-reinstall --no-deps "lumibot==X.Y.Z"`
   - Confirm the GitHub tag exists and points at the intended commit:
     - `git show -s vX.Y.Z`

6) **Downstream rollout (BotManager)**
   - Confirm BotManager is pinned to the new version and deploy workflows ran:

     ```bash
     gh variable set -R Lumiwealth/bot_manager LUMIBOT_VERSION -b "X.Y.Z"
     gh variable list -R Lumiwealth/bot_manager | rg '^LUMIBOT_VERSION'

     gh workflow run -R Lumiwealth/bot_manager "CI/CD - Development Environment" --ref main \
       -f force_rebuild_images=false -f skip_tests=false

     gh workflow run -R Lumiwealth/bot_manager "CI/CD - Production Environment" --ref prod \
       -f force_rebuild_images=false -f skip_tests=false

     gh run list -R Lumiwealth/bot_manager -L 10
     ```

7) **Start the next version branch**
   - Create `version/X.Y.(Z+1)` from `dev` (or from the just-deployed commit once it’s on `dev`).
   - Do not bump `setup.py` again until the next deployment.

---

## Common pitfalls (learned during 4.4.32)

- **Publishing to PyPI without pushing the `vX.Y.Z` tag first** breaks traceability.
  - The repo’s release workflow is tag-driven. If the version is already on PyPI, pushing the tag later will
    cause the publish step to fail (PyPI rejects re-uploading the same version), and the GitHub Release step
    may not run.
  - Fix for next time: **tag first, publish via the workflow**.
  - If you must backfill after a manual publish: either accept a failed publish job and create the GitHub Release
    manually, or add a dedicated “GitHub Release only” workflow (future improvement).
- **Perf claims without evidence** cause churn.
  - If a PR claims speedups, it must include: the exact benchmark command(s), measured before/after numbers, and
    profiler artifacts (e.g., YAPPI CSV path) or it doesn’t ship as “performance work”.
- **Use `python3`**, not `python` (macOS environments often don’t have `python`).
- **Wrap long commands** with `/Users/robertgrzesik/bin/safe-timeout …` to avoid hanging sessions.
- **Broker apitests are opt-in**:
  - Run with `pytest -m apitest …` and expect skips when the market is closed.
  - Tradier’s sandbox environment does not behave like a full live account for certain order lifecycle endpoints;
    design smoke tests to skip appropriately.

## Notes

- Avoid destructive git operations (`git checkout`, `git reset --hard`, `git stash`).
- Keep release bookkeeping changes small and explicit (version bump + changelog + tag/release).
