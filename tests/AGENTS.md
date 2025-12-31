# Tests Agent Instructions (Legacy Test Policy)

These rules apply to all files under `tests/`.

## Legacy tests are high-authority

- Treat any test whose **earliest commit date is before 2025-01-01** as **LEGACY**.
- For LEGACY tests, **fix the code, not the test**.
- Only change a LEGACY test when you can clearly justify that:
  - the old expectation was incorrect, or
  - behavior was intentionally changed for correctness (e.g., fixing lookahead bias),
  and you document it in the test file.

## Any test change must be explained

- If you change any expected values or assertions, add a short note near the change
  explaining **why** (what changed, and why the new expectation is correct).
- Prefer making the test more robust (less brittle) over updating magic numbers.

## CI guard for legacy edits

- CI should block edits to LEGACY tests unless the PR is explicitly approved.
  The recommended mechanism is a PR label + required write-up (see `.github/workflows/`).

