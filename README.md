# stonxx 🚀

### *The Institutional-Grade AI Trading System for Indian Equities*

[![Market: NSE/BSE](https://img.shields.io/badge/Market-NSE%2FBSE-orange?style=flat-square)](https://www.nseindia.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Powered By: XGBoost](https://img.shields.io/badge/Core-XGBoost-green?style=flat-square)](https://xgboost.readthedocs.io/)
[![LLM: Gemini + Llama](https://img.shields.io/badge/LLM-Gemini%20%7C%20Llama-purple?style=flat-square)](https://deepmind.google/technologies/gemini/)

**stonxx** is a high-conviction, automated trading framework specifically engineered for the **Indian Stock Market (NSE/BSE)**. It combines state-of-the-art machine learning with dual-layer LLM sentiment analysis to navigate the complexities of Indian market volatility with institutional precision.

---

## 💎 Why stonxx?

Most retail bots struggle with the "noise" of intraday trading and the high friction of the Indian market. **stonxx** solves this through:

-   **Deep ML Intelligence**: Built on an XGBoost engine trained on 10+ years (2015-2024) of NIFTY 15-minute historical data.
-   **Institutional Awareness**: Default configurations for ₹1 Crore+ portfolio management with realistic fee/slippage modeling (₹20 flat commission).
-   **Dual-Layer Veto System**: Every ML signal is cross-referenced against global macro sentiment (via **Google Gemini 2.5**) and local market news (via **Llama 3.2**).
-   **Native India Integration**: First-class support for **Dhan Broker** and intelligent Yahoo Finance fallback for backtesting.

---

## 🚀 Key Features

### 🧠 AI-Driven Execution
-   **Predictive Confidence**: Uses `predict_proba` with a strict **45% threshold** to minimize low-probability entries.
-   **Stationary Features**: Logic built on scale-invariant features (RSI, ATR ratios, VWAP distance), allowing the models to generalized from Nifty indices to individual liquid stocks.

### 🛡️ Risk Management Engine
-   **ATR-Based Sizing**: Dynamic position sizing based on Kelly-inspired ATR risk (1% portfolio risk per trade, capped at 15% allocation).
-   **Intraday Circuit Breaker**: Instant "Sell All & Halt" trigger if the portfolio drops >2% within a single session.
-   **Bracket Scaling**: Automated Take-Profit and Stop-Loss placements based on 1.5x and 1.0x ATR multiples.

### 📊 Real-Time Connectivity
-   **Paper Trade Alerts**: Live Telegram notifications for all order intents, entry, and exits.
-   **Local NLP Engine**: Runs local Llama 3.2 models (via Ollama) to scrape and analyze Indian financial press in real-time.

---

## 🛠️ Getting Started

### 1. Requirements
-   Python 3.10+
-   Ollama (for Llama 3.2 local sentiment)
-   DhanHQ API Credentials

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/algoplutus1708/stonxx.git
cd stonxx

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 3. Environment Configuration
Create a `.env.india` file in the root directory:
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

## 📈 Usage

### Run a Backtest
Validate the system on 2025 Out-of-Sample (OOS) data with realistic slippage:
```bash
python run_stonxx_backtest.py
```

### Start Paper Trading
Run the strategy in a safe paper environment with live Dhan data:
```bash
python daily_paper_trader.py
```

### Train the Model
Update the XGBoost artifact with the latest market data:
```bash
python train_nifty_model.py
```

---

## 🏗️ Project Architecture

```text
├── lumibot/                     # Core trading framework
│   ├── brokers/dhan.py          # Native Dhan integration
│   └── example_strategies/      # Main strategy logic (stonxx_india_bot.py)
├── data/                        # Local CSV datasets (NIFTY 15-min)
├── dataset/                     # Processed feature matrices
├── nifty_xgb_model.joblib       # Trained ML artifact
├── sentiment_engine.py          # Dual LLM sentiment logic
└── run_stonxx_backtest.py       # High-fidelity backtest runner
```

---

## 🛡️ Risk Disclaimer

Trading in the Indian stock market involves significant risk. **stonxx** is an experimental tool. Past performance, even on high-fidelity out-of-sample data, does not guarantee future results. Use institutional-grade risk management and never trade capital you cannot afford to lose.

---

**Crafted with ❤️ for the Indian Quant community.**
