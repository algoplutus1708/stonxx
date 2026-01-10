# DEPLOYMENT

> Release/deployment workflow for LumiBot (version branches, changelog, tags, and GitHub releases).

**Last Updated:** 2026-01-09  
**Status:** Active  
**Audience:** Developers + AI Agents

---

## Goals

- Make deployments traceable (what code was deployed, when, and why).
- Keep multi-agent collaboration safe (shared `version/*` branches).
- Avoid “version drift” between deployed artifacts and `setup.py`.

---

## Branch + Version Rules (STRICT)

- Active work happens on a shared version branch: `version/X.Y.Z` (example: `version/4.4.31`).
- **Do not create extra branches** off a version branch unless explicitly instructed.
- **Do not bump** `setup.py` version just because work started.
  - Version bump happens at deployment time only.

---

## Deployment Checklist (Recommended)

1) **Verify tests**
   - Ensure required CI checks are green (unit + backtest + acceptance gates as applicable).

2) **Bump version (deploy-marker commit)**
   - Update `setup.py` `version="X.Y.Z"`.
   - Commit with message: `deploy X.Y.Z`.
   - This is the commit the release tag should point at.

3) **Human deploy step (PyPI / production)**
   - A human runs the actual deployment/publish step (e.g., build + publish to PyPI, and any internal rollout).
   - AI agents **must not** attempt to deploy.

4) **Update changelog (FULL RANGE, not just “recent work”)**
   - Add/refresh the `CHANGELOG.md` entry for `X.Y.Z`.
   - Include: `Deploy marker: <commit>` referencing the `deploy X.Y.Z` commit hash.
   - The entry must include **all significant commits** since the previous `setup.py` version bump:
     - Find the previous bump commit:
       - `git log -p -- setup.py`
     - Build the changelog from the full range:
       - `git log --oneline <previous-bump-commit>..<deploy-marker-commit>`
   - If the version branch was already merged into `dev` before the changelog is complete, add the changelog fix as a follow-up PR to `dev`.

5) **Tag the deploy commit**
   - Create an annotated tag `vX.Y.Z` pointing at the `deploy X.Y.Z` commit.
   - Push the tag to GitHub.

6) **Create a GitHub Release**
   - Create a GitHub Release from tag `vX.Y.Z`.
   - Paste the corresponding `CHANGELOG.md` entry.

7) **Start the next version branch**
   - Create `version/X.Y.(Z+1)` from `dev` (or from the just-deployed commit once it’s on `dev`).
   - Do not bump `setup.py` again until the next deployment.

---

## Notes

- Avoid destructive git operations (`git checkout`, `git reset --hard`, `git stash`).
- Keep release bookkeeping changes small and explicit (version bump + changelog + tag/release).
