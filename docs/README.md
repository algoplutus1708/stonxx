# Documentation

This folder contains **human-authored** documentation (architecture, investigations, handoffs, ops notes).

## Quick Links

| Document | Purpose |
|----------|---------|
| `BACKTESTING_ARCHITECTURE.md` | **Start here** - Data flow and architecture |
| `../CHANGELOG.md` | **Deployment history** - Must be updated every release |
| `ENV_VARS.md` | Environment variable reference |
| `ACCEPTANCE_BACKTESTS.md` | Release gate criteria |

## Changelog Maintenance (MANDATORY)

**`../CHANGELOG.md` MUST be updated with every deployment.**

### When to Update

- Deployments to production
- Version bumps / releases
- Bug fixes (especially data source, split, dividend fixes)
- New features
- Breaking changes (mark with ⚠️)

### Format

```markdown
## X.Y.Z - YYYY-MM-DD

### Added / Changed / Fixed / Deprecated / Removed / Security
- Description of change
```

### Pre-Deployment Checklist

- [ ] Changelog entry added with current date
- [ ] Version number updated
- [ ] Breaking changes clearly marked

See `AGENTS.md` and `CLAUDE.md` for full requirements.

---

## Directory Structure

- **Handoffs:** `handoffs/` - Cross-session coordination notes
- **Investigations:** `investigations/` - Deep dives and root-cause analyses
- **Naming convention:** `YYYY-MM-DD_<topic>.md` for chronological sorting

## Public Documentation Site

- `docsrc/` contains the Sphinx source
- `generated-docs/` is local build output (gitignored)
- GitHub Actions builds + deploys Pages on pushes to `dev`
