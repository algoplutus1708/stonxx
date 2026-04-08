import pandas as pd
import numpy as np
import yfinance as yf
import joblib
import ollama
import feedparser
import re
import warnings
warnings.filterwarnings("ignore")

def calculate_features(df):
    """
    Computes required indicators (RSI, MACD, ATR, Lagged Returns)
    and drops all raw price variables and NaN samples.
    """
    df = df.copy()
    
    # 1. Construct Target
    valid_next_mask = df['close'].shift(-1).notna() & df['open'].shift(-1).notna()
    df['target'] = np.where(df['close'].shift(-1) > df['open'].shift(-1), 1.0, 0.0)
    df.loc[~valid_next_mask, 'target'] = np.nan
    
    # 2. RSI (14-period) using Wilder's EMA weighting
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # 3. MACD, Signal, Histogram
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # 4. ATR (14-period) normalized by close price
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    df['atr_14_norm'] = atr / df['close']
    
    # 5. Lagged Returns
    daily_returns = df['close'].pct_change()
    df['return_lag_1'] = daily_returns.shift(1)
    df['return_lag_2'] = daily_returns.shift(2)
    df['return_lag_3'] = daily_returns.shift(3)
    
    # Drop NaNs
    df.dropna(inplace=True)
    df['target'] = df['target'].astype(int)
    
    # Crucial: Drop raw prices and unnormalized columns
    cols_to_drop = ['open', 'high', 'low', 'close', 'volume']
    df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True)
    
    return df

def get_technical_prediction():
    model = joblib.load("nifty_daily_model.joblib")
    
    # Fetch latest 100 days
    df = yf.download("^NSEI", period="100d", interval="1d", progress=False)
    
    # Handle yfinance multiindex layout and normalize naming
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.droplevel(1)
        except Exception:
            df.columns = [col[0] for col in df.columns]
            
    df.columns = [str(col).lower() for col in df.columns]
    cols_to_keep = ['open', 'high', 'low', 'close', 'volume']
    df = df[[c for c in cols_to_keep if c in df.columns]]
    
    last_close = df.iloc[-1]['close']
    
    # Append mock day to prevent dropna() erasing the absolute latest day's calculation
    raw_df = df.copy()
    new_idx = raw_df.index[-1] + pd.Timedelta(days=1)
    raw_df.loc[new_idx] = raw_df.iloc[-1]
    
    features_df = calculate_features(raw_df)
    latest = features_df.iloc[-1]
    
    required_features = ['rsi_14', 'macd', 'macd_signal', 'macd_hist', 'atr_14_norm', 'return_lag_1', 'return_lag_2', 'return_lag_3']
    x_input = pd.DataFrame([latest[required_features]])
    
    # Probability that tomorrow goes UP (target == 1)
    prob_up = model.predict_proba(x_input)[0][1]
    current_atr = latest['atr_14_norm']
    
    # Extract native scalar out of numpy/pandas series if necessary
    last_close = float(last_close.iloc[0] if isinstance(last_close, pd.Series) else last_close)
    
    return last_close, prob_up, current_atr

def get_live_news():
    url = "https://www.moneycontrol.com/rss/latestnews.xml"
    feed = feedparser.parse(url)
    
    titles = []
    for entry in feed.entries[:10]:
        titles.append(entry.title)
        
    return " | ".join(titles)

def get_market_sentiment(headlines, model_name='llama3.2'):
    prompt = f"""Role: Expert Indian Stock Market Quantitative Analyst.
Task: Analyze the provided headlines and rate the macroeconomic sentiment on a strict scale from -1.0 (extreme panic/bearish) to 1.0 (extreme euphoria/bullish). 0.0 is neutral.
Constraint: Respond WITH ONLY THE NUMBER. Do not include text.

Headlines:
{headlines}
"""
    try:
        response = ollama.chat(model=model_name, messages=[
            {'role': 'user', 'content': prompt}
        ])
        raw_output = response['message']['content'].strip()
        
        match = re.search(r'-?\d+\.?\d*', raw_output)
        if match:
            return max(-1.0, min(1.0, float(match.group())))
        return 0.0
    except Exception as e:
        print(f"Ollama failure: {e}")
        return 0.0

if __name__ == "__main__":
    print("-" * 65)
    print("        STONXX LIVE DAILY PAPER TRADER - AI ENSEMBLE        ")
    print("-" * 65)
    
    print("\n[1] Firing Technical Engine (XGBoost)...")
    try:
        last_close, prob_up, current_atr = get_technical_prediction()
        print(f"    Nifty 50 Last Close : {last_close:,.2f}")
        print(f"    Upward Probability  : {prob_up:.2%}")
        print(f"    Current ATR (Norm)  : {current_atr:.5f}")
    except Exception as e:
        print(f"    [Error] Technical Engine Failed: {e}")
        exit(1)
        
    print("\n[2] Firing Sentiment Engine (Ollama: llama3.2)...")
    try:
        headlines = get_live_news()
        sentiment = get_market_sentiment(headlines)
        clean_headline = headlines.replace('\n', ' ')[:80]
        print(f"    Top Headlines Snippet : {clean_headline}...")
        print(f"    Macro Sentiment Score : {sentiment:+.2f} (-1.0 to 1.0)")
    except Exception as e:
        print(f"    [Error] Sentiment Engine Failed: {e}")
        exit(1)
        
    print("\n[3] Combinative Inference Engine:")
    
    # Verdict Logic
    if prob_up > 0.54 and sentiment > 0.2 and current_atr > 0.005:
        verdict = "STRONGLY BULLISH - BUY NIFTY"
    elif prob_up > 0.54 and sentiment < 0.0:
        verdict = "WARNING: Math is bullish, but News is negative. STAY FLAT."
    elif prob_up < 0.50 and sentiment < -0.2:
        verdict = "STRONGLY BEARISH - SELL/FLAT"
    else:
        verdict = "NO CLEAR EDGE - STAY IN CASH"
        
    print("=" * 65)
    print(f"FINAL VERDICT : {verdict}")
    print("=" * 65)
    print()
