"""
train_mock_ml_model.py
======================
This is a helper script to train and save a basic mock XGBoost model.
It generates random dummy data shaped like our technical indicators 
(RSI, MACD, ATR) and trains a quick model. 

Run this ONCE to locally generate the `nifty_xgb_model.joblib` file 
required by your EnsembleTrader strategy!
"""

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score

def train_and_save_model():
    print("Generating simulated historical feature data...")
    # Features required by our strategy: "RSI_14", "MACD_12_26_9", "ATRr_14"
    num_samples = 2000
    
    # Simulate RSI between 10 and 90
    rsi = np.random.uniform(10, 90, num_samples)
    
    # Simulate MACD values around 0
    macd = np.random.uniform(-5, 5, num_samples)
    
    # Simulate ATR (volatility) between 10 and 150 points
    atr = np.random.uniform(10, 150, num_samples)
    
    # Combine into a DataFrame
    X = pd.DataFrame({
        "RSI_14": rsi,
        "MACD_12_26_9": macd,
        "ATRr_14": atr
    })
    
    # Simulate standard trading logic: 
    # Let's pretend our model learns to Buy (1) if RSI is above 40 and MACD is positive.
    # Otherwise Sell/Hold (0).
    y = np.where((X["RSI_14"] > 40) & (X["MACD_12_26_9"] > 0), 1, 0)
    
    # Introduce a little bit of noise so it's a realistic ML problem
    noise = np.random.choice([0, 1], size=num_samples, p=[0.9, 0.1])
    y = np.bitwise_xor(y, noise)
    
    # Split for validation
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"Training Random Forest Classifier on {len(X_train)} samples...")
    model = RandomForestClassifier(
        n_estimators=100, 
        max_depth=5, 
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print("\n--- Model Performance Results ---")
    print(f"Accuracy: {acc:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    print("---------------------------------\n")

    # Save the model
    filename = "nifty_xgb_model.joblib"
    joblib.dump(model, filename)
    print(f"✅ Success! Saved compiled model to: {filename}")
    print("You can now successfully run python run_ensemble_live.py")

if __name__ == "__main__":
    train_and_save_model()
