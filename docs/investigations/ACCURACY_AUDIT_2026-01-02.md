# Acceptance Backtests — Accuracy Audit Notes (2026-01-02)

This is a structured, human-readable audit checklist for the ThetaData acceptance suite.

Scope:
- LumiBot `4.4.21` local runs
- Production-like flags (`BACKTESTING_QUIET_LOGS=false`, progress bar on, plots/indicators/tearsheet on)
- Remote downloader: `DATADOWNLOADER_BASE_URL=http://data-downloader.lumiwealth.com:8080`
- Artifacts written to `Strategy Library/logs/`

These notes are intentionally “what to look for” + “what I observed”, not hard assertions.

Acceptance gate definition lives in: `docs/ACCEPTANCE_BACKTESTS.md`.

## AAPL Deep Dip Calls (Copy 4)

- Run id: `AAPLDeepDipCalls_2026-01-02_10-25_3KsjXy`
- Runtime: ~4m (under 15m gate)
- Trade sanity:
  - Multiple buy entries observed (meets “dip eras” expectation).
  - Prices/fills use option quotes (limit buys at ask); no obvious “split cliff” behavior observed.
- Notable warnings:
  - End-of-window data gaps around late Nov 2025 produced forward-fill warnings; these are expected for illiquid options and should not create sawtooth PV.

## Alpha Picks LEAPS (Buy Hold)

Short window (must trade UBER/CLS/MFC):
- Run id: `LeapsCallDebitSpread_2026-01-02_10-07_OZi6We`
- Trade sanity:
  - UBER, CLS, and MFC all opened with *two legs* (buy long call + sell short call).
  - Both legs filled with limit orders using bid/ask anchors from `OptionsHelper.evaluate_option_market()`.

Full-year window (artifacts + skip reasons):
- Run id: `LeapsCallDebitSpread_2026-01-02_10-48_4UtvLT`
- Trade sanity:
  - Strategy may skip some symbols depending on quote availability; skip reasons are logged.

## TQQQ SMA200

ThetaData:
- Run id: `TqqqSma200Strategy_2026-01-02_10-24_Uus6vb`
- Reported CAGR ~0.409 (close to prior anchors).

Yahoo (parity check):
- Run id: `TqqqSma200Strategy_2026-01-02_10-25_fOI4Ek`
- Reported CAGR ~0.409; close to ThetaData result (no obvious inflation).

## Backdoor Butterfly 0DTE (regular market fills)

- Run id: `BackdoorButterfly0DTE_2026-01-02_10-29_HPNuUM`
- Strategy CAGR ≈ `-20.79%` (matches historical expectation: “regular fills get punished by spread”).
- Fill sanity:
  - Option marks/quotes appear bid/ask-driven; no mid-price “cheating” observed for market fills.

## Backdoor Butterfly 0DTE (SmartLimit)

- Run id: `BackdoorButterfly0DTESmartLimit_2026-01-02_10-34_UTFoHq`
- Strategy CAGR ≈ `-2.96%` (SmartLimit improves results vs regular fills, as expected).
- Fill sanity:
  - SmartLimit behavior appears to use quote-derived mid + slippage (net multi-leg), not bid/ask worst-case.

## MELI Deep Drawdown Calls

- Run id: `MeliDeepDrawdownCalls_2026-01-02_10-09_7yisFp`
- Runtime: ~14m (under 15m gate)
- Trade sanity:
  - Drawdown-triggered entries occur (multiple option buys).
  - Exits near expiration can cancel when quotes are not actionable; positions then cash-settle at expiration (expected for illiquid strikes).
- MTM sanity:
  - No sawtooth PV observed during this run (option marks are forward-filled when quotes are intermittently missing).
- Anchor mismatch (needs human sign-off):
  - Prior “known-good” artifact `MeliDeepDrawdownCalls_2025-12-25_20-38_33bGtY_tearsheet.csv` reports Strategy CAGR ≈ `+7.26%`.
  - This run reports Strategy CAGR ≈ `-18.22%`.
  - Trade list diverges materially starting in 2021 (expiration selection differs for some entries).
  - Hypothesis: expiration validation now prefers actionable intraday NBBO snapshots, changing which expirations are considered tradeable at historical dates. This should improve realism, but it changes results and should be explicitly re-baselined if accepted.

## SPX Short Straddle Intraday

- Run id: `SPXShortStraddle_2026-01-02_10-39_XtAwjW`
- Runtime: ~8m40s (under 15m gate; warm cache)
- Stall sanity:
  - No “silent” wedges observed locally.
  - Queue client emits submit/result logs continuously; in production, the same codepath emits heartbeat logs during longer waits (to avoid silent stalls).
