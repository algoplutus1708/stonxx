## SMART_LIMIT live testing (paper)

This repo has two layers of coverage:

- **Unit tests** (deterministic): validate SMART_LIMIT math + state machine behavior without broker APIs.
- **API tests** (`pytest -m apitest`): place real paper orders to validate submission + repricing + fills.

### 1) One-time setup

- Put broker creds in `.env` (repo root). The tests load it automatically.

### 2) Run unit tests (any time)

```bash
/Users/robertgrzesik/bin/safe-timeout 1200s python3 -m pytest -q \
  tests/test_smart_limit_utils_unit.py \
  tests/test_smart_limit_single_leg_unit.py \
  tests/test_smart_limit_multileg_unit.py \
  tests/test_tradier_stream_optional_unit.py
```

### 3) Run live paper smoke (market hours)

These are “fast confidence” tests (stocks + single-leg options + 4-leg options) and should complete quickly.

```bash
/Users/robertgrzesik/bin/safe-timeout 2400s python3 -m pytest -q -m "apitest and not smartlimit_matrix" \
  tests/test_alpaca_broker_smoke_apitest.py \
  tests/test_tradier_broker_smoke_apitest.py \
  tests/test_smart_limit_live_alpaca.py \
  tests/test_smart_limit_live_tradier.py
```

### 4) Run live matrix (market hours)

These are heavier tests that add:

- debit + credit multi-leg packages (condor + butterfly)
- puts + long-dated options (wider spreads)
- short options (skips if broker rejects)
- non-SMART multi-leg LIMIT UX parity (no debit/credit/even in strategy code)

```bash
/Users/robertgrzesik/bin/safe-timeout 7200s python3 -m pytest -q -m smartlimit_matrix \
  tests/test_smart_limit_live_matrix_alpaca.py \
  tests/test_smart_limit_live_matrix_tradier.py
```

### 5) Benchmarks (market hours; not a pytest)

Benchmarks are in `scripts/` and write CSVs to `logs/`. These are used for price-improvement statistics and are not
treated as strict pass/fail (paper fills can be unrealistic).
