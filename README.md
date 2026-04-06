# Lumibot - Indian Stock Market Edition 🇮🇳

[![CI Status](https://github.com/algoplutus1708/lumibot/actions/workflows/cicd.yaml/badge.svg?branch=main)](https://github.com/algoplutus1708/lumibot/actions/workflows/cicd.yaml)

LumiBot is an institutional-grade backtesting and trading library now fully localized for the **Indian Stock Market (NSE/BSE)**. This fork includes native support for the **Dhan Broker**, enabling seamless transitions from backtesting to live execution on Indian exchanges.

## 🚀 Key Indian Market Features

- **Native Dhan Integration**: Direct trading via the DhanHQ API (NSE, BSE, F&O).
- **Cost-Optimized Data**: Built-in fallback to **Yahoo Finance (`yfinance`)** for historical NSE/BSE data, bypassing the need for paid historical data plans for backtesting.
- **Indian Market Awareness**: Full support for IST (9:15 AM - 3:30 PM) trading sessions and standard Indian holidays.
- **MIS & Product Logic**: Built-in handling for Intraday (MIS) square-off times (e.g., auto-exit before 3:15 PM).

---

## 🛠️ Getting Started in India

### 1. Environment Setup

Copy the example configuration files and add your Dhan credentials:

```bash
# Core Indian market configuration
cp .env.india.example .env.india

# Secret management (API keys, etc.)
mkdir -p .secrets
cp .secrets/lumi_secrets.env.example .secrets/lumi_secrets.env
```

### 2. Installation

Install the required dependencies, including the `dhanhq` library:

```bash
pip install -r requirements.txt
pip install -e .
```

### 3. Run Your First Indian Backtest

Run the provided example strategy on NSE stocks like RELIANCE:

```bash
python run_india_backtest.py
```

---

## 🏗️ Architecture

- `lumibot/brokers/dhan.py` - Custom Dhan broker implementation.
- `lumibot/data_sources/dhan_data.py` - Data source with intelligent Yahoo Finance fallback for India.
- `lumibot/example_strategies/india_ai_momentum.py` - Example momentum strategy with MIS square-off rules.
- `Dockerfile.india` & `docker-compose.india.yml` - Ready-to-use Docker environment for deployment.

---

## 🛡️ Security & Privacy

This repository is configured with a robust `.gitignore` to ensure your `.env` files and the `.secrets/` directory are never pushed to GitHub. Always use the `.example` files as templates for sharing structure without leaking credentials.

## 📖 Learn More

LumiBot's core documentation is available at [lumibot.lumiwealth.com](http://lumibot.lumiwealth.com/). For Indian-market specific questions, please refer to the `docs/` folder in this repository.

---

**Built with ❤️ for Indian Traders.**
