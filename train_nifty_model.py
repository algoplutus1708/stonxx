"""
train_nifty_model.py
====================
Institutional-grade script to train our Ensemble strategy's XGBoost model 
using real 15-minute historical NIFTY 50 data.

This script:
1. Loads historical CSV data from the `data/` folder.
2. Calculates RSI, MACD, and ATR features using `pandas_ta`.
3. Targets a 4-bar (1-hour) forward positive return.
4. Trains a RandomForestClassifier (robust alternative to XGBoost for this setup).
5. Saves the model to `nifty_xgb_model.joblib`.
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
import joblib
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score

def train_production_model():
    csv_path = "data/NIFTY 50_15minute.csv"
    if not os.path.exists(csv_path):
        print(f"CRITICAL: {csv_path} not found.")
        return

    print(f"Loading historical data from {csv_path}...")
    df = pd.read_csv(csv_path)
    
    # Ensure columns are standard
    df.columns = [c.lower() for c in df.columns]
    
    # Check for date column and sort
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df.sort_values('date', inplace=True)
    
    print(f"Processing {len(df)} bars of NIFTY data...")

    # --- FEATURE ENGINEERING (Must match EnsembleTrader strategy) ---
    # 1. 14-period RSI
    df.ta.rsi(length=14, append=True)
    
    # 2. MACD (12, 26, 9)
    # This creates MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    
    # 3. 14-period ATR
    # This usually creates ATR_14, but we'll map it to ATRr_14 if needed
    df.ta.atr(length=14, append=True)
    
    # Mapping pandas_ta names to our strategy's expected names
    # Strategy expects: ["RSI_14", "MACD_12_26_9", "ATRr_14"]
    if "ATRr_14" not in df.columns and "ATR_14" in df.columns:
        df.rename(columns={"ATR_14": "ATRr_14"}, inplace=True)

    # --- TARGET LABELING ---
    # We want to predict if the price will be higher 1 hour (4 x 15-min bars) from now.
    prediction_horizon = 4 
    df['target'] = (df['close'].shift(-prediction_horizon) > df['close']).astype(int)

    # Drop NaNs from indicator lookback and shift
    df.dropna(inplace=True)

    # Final feature set
    features = ["RSI_14", "MACD_12_26_9", "ATRr_14"]
    X = df[features]
    y = df['target']

    # --- TRAINING ---
    # We use a TimeSeriesSplit-friendly approach (train on past, test on future)
    # instead of a random split for financial data.
    train_size = int(len(X) * 0.8)
    X_train, X_test = X[:train_size], X[train_size:]
    y_train, y_test = y[:train_size], y[train_size:]

    print(f"Training on {len(X_train)} samples...")
    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=6,
        min_samples_leaf=20,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    # --- EVALUATION ---
    y_pred = model.predict(X_test)
    print("\n" + "="*40)
    print("PRODUCTION MODEL PERFORMANCE (OOO TEST SET)")
    print("="*40)
    print(f"Accuracy Score: {accuracy_score(y_test, y_pred):.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    # Feature Importance
    importances = model.feature_importances_
    for name, importance in zip(features, importances):
        print(f"Feature '{name}' Importance: {importance:.4f}")
    print("="*40 + "\n")

    # --- SAVE ---
    model_filename = "nifty_xgb_model.joblib"
    joblib.dump(model, model_filename)
    print(f"✅ REAL DATA MODEL successfully saved to: {model_filename}")

if __name__ == "__main__":
    train_production_model()
