import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import joblib
import glob

# 1. Load the Normalized YF Data
files = glob.glob('data/*yf.parquet')
if not files:
    print("[CRITICAL] No YF parquet file found. Run yf_historical_fetcher.py first.")
    exit(1)

file_path = max(files, key=os.path.getctime)
print(f"[INFO] Loading data from: {file_path}")
df = pd.read_parquet(file_path)

# 2. Feature Engineering (The Data Contract)
# IMPORTANT: This exact function must be copy-pasted into your live trading strategy later.
def calculate_features(data):
    df = data.copy()
    df['returns'] = df['close'].pct_change()
    df['sma_10'] = df['close'].rolling(window=10).mean()
    df['sma_30'] = df['close'].rolling(window=30).mean()
    df['volatility'] = df['returns'].rolling(window=10).std()
    
    # Basic RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

df = calculate_features(df)

# 3. Target Variable
# Will the NEXT 15-min candle close higher than its open? (1 = Up, 0 = Down)
df['target'] = (df['close'].shift(-1) > df['open'].shift(-1)).astype(int)

# Drop NaNs caused by rolling windows and shifting
df.dropna(inplace=True)

features = ['returns', 'sma_10', 'sma_30', 'volatility', 'rsi']
X = df[features]
y = df['target']

# 4. Time-Series Validation (No Look-Ahead Bias)
tscv = TimeSeriesSplit(n_splits=5)
model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42)

print("\n--- TimeSeries Validation ---")
for train_index, test_index in tscv.split(X):
    X_train, X_test = X.iloc[train_index], X.iloc[test_index]
    y_train, y_test = y.iloc[train_index], y.iloc[test_index]
    
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"Fold Accuracy: {acc * 100:.2f}%")

# 5. Train Final Model & Export
print("\n[INFO] Training final model on full 60-day dataset...")
model.fit(X, y)
joblib.dump(model, 'nifty_yf_model.joblib')
print("[SUCCESS] Model saved to nifty_yf_model.joblib")