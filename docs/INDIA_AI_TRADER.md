# India AI Trader — Architecture & Ops Guide

The Indian Stock Market AI Algorithmic Trading Agent is an institutional-grade, fully automated trading system optimized for the NSE (National Stock Exchange) and BSE (Bombay Stock Exchange).

This agent uses the Gemini AI model (via LumiBot's native `agents` framework) to analyze the market, read the news, evaluate technical indicators, and autonomously manage a portfolio of Indian equities.

## System Architecture

The India AI Trader stack consists of three main components:

1.  **Dhan Broker (`lumibot.brokers.dhan.Dhan`)**
    *   Fully implements the `Broker` interface for live execution.
    *   Polls Dhan APIs for order status updates (bypassing the lack of retail WebSockets).
    *   Monitors margin limits and properly submits `INTRA` (MIS), `CNC` (Delivery), or `MARGIN` (NRML) orders based on the configuration.
2.  **Dhan Data Source (`lumibot.data_sources.dhan_data.DhanData`)**
    *   Automatically translates NSE symbols like `RELIANCE` to exchange-specific formats (`RELIANCE.NS` for YFinance, `NSE_EQ` for Dhan).
    *   Backtesting is powered by Yahoo Finance, acting as a drop-in replacement via the backtesting engine hooks.
3.  **IndiaAITrader Strategy (`lumibot.example_strategies.india_ai_trader.IndiaAITrader`)**
    *   Leverages the Gemini AI model to rank opportunities and execute trades.
    *   Includes 5 powerful `@agent_tool` functions out-of-the-box:
        *   `get_nse_bars`: OHLCV data.
        *   `get_nifty_movers`: Market breadth indicators.
        *   `get_india_market_news`: Economic Times RSS headlines.
        *   `get_technical_signals`: Supertrend and VWAP indicators.
        *   `get_portfolio_stats`: Risk and capital management.

## Default Operations & Safety Hooks

> [!IMPORTANT]
> The default product type is `MIS` (Intraday), which leverages broker leverage but strictly prevents holding positions overnight.

To ensure stability in a production environment:
-   **Market Guards:** `IndiaAITrader` prevents entering trades during the pre-open session and forces AI processing to adhere to standard continuous market hours (09:15 - 15:30 IST).
-   **Forced MIS Square-off:** A safety hook explicitly fires at 15:15 IST (5 minutes before Dhan's auto-square-off) to aggressively market-sell all lingering intraday positions, ensuring the agent maintains strict control over exits.
-   **Position Sizing:** Position size is constrained by `RISK_PER_TRADE_PCT` and `MAX_POSITIONS`.

## Quick Start (Backtest)

To test the AI Agent over historical data:

1.  Ensure you have a Gemini API key from Google AI Studio.
2.  Create `.env.india`:
    ```bash
    cp .env.india.example .env.india
    ```
3.  Set your API key in `.env.india`:
    ```env
    GOOGLE_API_KEY=your_gemini_api_key
    ```
4.  Run the test:
    ```bash
    python run_india_backtest.py
    ```

## Daily Panel Research Workflow

For the swing-trading baseline, use the closed-bar daily Yahoo panel instead of
intraday broker history. The research loop is:

1.  Download the split-adjusted stock panel plus Nifty benchmark:
    ```bash
    python yf_historical_fetcher.py
    ```
2.  Train the daily baseline model with expanding walk-forward splits and a
    5-trading-day embargo:
    ```bash
    python train_yf_model.py
    ```

The fetcher writes `data/stonxx_daily_panel_yf.parquet`. The trainer reads that
panel, computes long-only ranking features such as normalized momentum, `rsi_5`,
and benchmark-relative alpha, then saves `stonxx_daily_panel_model.joblib`.

Important operating assumptions:

-   Yahoo prices are downloaded with split/dividend adjustment enabled by default.
-   The model is trained only on fully closed daily bars. Do not feed unfinished
    intraday snapshots into this baseline without retraining on matching inputs.
-   Validation is date-based across the whole stock panel, so every fold obeys
    `train_end < validation_start`.

## Live Deployment

Running the agent live requires a Dhan trading account and API credentials.

1.  Set your Dhan API keys in `.env.india`:
    ```env
    DHAN_CLIENT_ID=your_id
    DHAN_ACCESS_TOKEN=your_token
    ```
2.  Modify the target `STRATEGY_UNIVERSE` in the `.env` to select which stocks the agent should scan.
3.  Execute the live runner:
    ```bash
    python run_india_live.py
    ```

> [!WARNING]
> While running live, strictly monitor real-time order fills during the first few market sessions to ensure the agent's risk appetite aligns with your account's margin limits.

## Suggested Extensions

-   **Derivatives Support:** Expand the `STRATEGY_UNIVERSE` to include F&O symbols like `NIFTY` or `BANKNIFTY` and update the `get_nse_bars` tool to request data from Dhan's historical API for futures instead of Yahoo Finance.
-   **Custom Knowledge:** Bind additional `@agent_tool` endpoints to parse RBI policy documents, fetch FII/DII flow statistics, or ingest custom momentum data for enhanced AI context.
