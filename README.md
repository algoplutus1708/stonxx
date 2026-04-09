# stonxx 🚀

### *The Institutional-Grade AI Trading System for Indian Equities*

[![Market: NSE/BSE](https://img.shields.io/badge/Market-NSE%2FBSE-orange?style=flat-square)](https://www.nseindia.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Core: XGBoost](https://img.shields.io/badge/Core-XGBoost-green?style=flat-square)](https://xgboost.readthedocs.io/)
[![LLM: Gemini + Llama](https://img.shields.io/badge/LLM-Gemini%20%7C%20Llama-purple?style=flat-square)](https://deepmind.google/technologies/gemini/)
[![Maintainer: swastick](https://img.shields.io/badge/Maintained%20by-swastick-brightgreen?style=flat-square)](#authors)

**stonxx** is a high-conviction, automated trading framework specifically engineered for the **Indian Stock Market (NSE/BSE)**. Created and maintained by **swastick**, it combines state-of-the-art machine learning with dual-layer LLM sentiment analysis to navigate the complexities of Indian market volatility with institutional precision.

---

## 💎 Why stonxx?

Retail trading in the Indian market is often a battle against noise, high slippage, and emotional bias. **stonxx** is designed to pivot away from low-probability intraday scalping towards high-conviction **Daily Swing Trading**.

-   **Deep ML Intelligence**: Built on an XGBoost engine trained on 10+ years (2015-2024) of NIFTY 15-minute and Daily historical data.
-   **Institutional Awareness**: Optimized for ₹1 Crore+ portfolio management with realistic fee/slippage modeling (₹20 flat commission per leg).
-   **Dual-Layer Veto System**: Every ML signal is cross-referenced against global macro sentiment (via **Google Gemini 2.5 Flash**) and local market news (via **Llama 3.2**).
-   **Native India Integration**: First-class support for **Dhan Broker** via LumiBot, with intelligent fallback to Yahoo Finance for high-fidelity backtesting.
-   **Persistent Memory Bank**: Uses a local state manager to ensure active trades are tracked across bot restarts and crashes.

---

## 🚀 Key Features

### 🧠 AI-Driven Execution
-   **Predictive Confidence**: Uses `predict_proba` with a strict **45% threshold** to minimize low-probability entries.
-   **Strictly Stationary Features**: Logic ignores raw prices, focusing on scale-invariant features:
    -   *Log Returns & Volatility (20-bar std)*
    -   *Volume Pressure (Buying vs Selling pressure ratio)*
    -   *ATR Percentage & Bollinger Band Width*
    -   *VWAP Distance & 200 EMA Trend Alignment*

### 🛡️ Institutional Risk Engine
-   **ATR-Based Kelly Sizing**: Dynamic position sizing based on 1% portfolio risk per trade, capped at a maximum 15% allocation per asset.
-   **Automatic Bracket Orders**: Hardcoded Take-Profit (1.5x ATR) and Stop-Loss (1.0x ATR) for every entry.
-   **Intraday Circuit Breaker**: Instant "Sell All & Halt" trigger if the total portfolio drops more than 2% within a single trading session.

### 📊 Real-Time Operations
-   **Live Terminal Dashboard**: A `rich`-powered terminal interface for monitoring signals, active trades, and recent history.
-   **Paper Trade Alerts**: Automatic Telegram notifications for every order intent, entry, and exit.
-   **Local NLP Pipeline**: Scrapes Indian financial press and analyzes sentiment locally using Llama 3.2 (via Ollama).

---

## 🏗️ Project Architecture

```text
├── lumibot/                     # Core trading framework
│   ├── brokers/dhan.py          # Native Dhan HQ API integration
│   ├── example_strategies/      
│   │   ├── stonxx_india_bot.py  # Main strategy logic (XGB + LLM)
│   │   └── state_manager.py     # Memory Bank: persistence for trades
├── data/                        # Local CSV datasets (NIFTY 15-min)
├── dataset/                     # Processed feature matrices
├── nifty_xgb_model.joblib       # Trained ML artifact (XGBoost)
├── sentiment_engine.py          # Dual LLM sentiment analysis logic
├── stonxx_dashboard.py          # Live terminal UI (Rich-based)
├── run_stonxx_backtest.py       # High-fidelity backtest runner
└── daily_paper_trader.py        # Live paper trading runner
```

---

## 🛠️ Getting Started

### 1. Requirements
-   Python 3.10+
-   Ollama (Required for local Llama 3.2 sentiment)
-   DhanHQ API Access

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/algoplutus1708/stonxx.git
cd stonxx

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 3. Setup Environment
Create a `.env.india` file in the root:
```env
# Dhan Credentials
DHAN_CLIENT_ID="your_id"
DHAN_ACCESS_TOKEN="your_token"

# LLM Keys
GEMINI_API_KEY="your_google_key"

# Alerts
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"
```

---

## 📈 Usage Guide

### 1. Backtesting
Test the strategy on historical data with realistic Indian market fees (Tax, GST, STT simulated):
```bash
python run_stonxx_backtest.py
```

### 2. Live/Paper Trading
Start the bot in paper trading mode. It will scan the market every 15 minutes but execute based on Daily Swing signals:
```bash
python daily_paper_trader.py
```

### 3. Monitoring Dashboard
In a separate terminal, launch the live dashboard to see real-time probabilities and active positions:
```bash
python stonxx_dashboard.py
```

### 4. Model Training
Refresh the machine learning model using the latest NIFTY data:
```bash
python train_nifty_model.py
```

---

## 👤 Authors

- **swastick** (@algoplutus1708) — Lead Developer & Quant Strategist

---

## 🛡️ Risk Disclaimer

Trading in the Indian stock market involves significant risk. **stonxx** is an experimental tool. Past performance, even on high-fidelity out-of-sample data, does not guarantee future results. Use institutional-grade risk management and never trade capital you cannot afford to lose.

---

**Crafted with ❤️ for the Indian Quant community.**
