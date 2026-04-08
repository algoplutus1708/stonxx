import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score

def calculate_features(df):
    """
    Computes required indicators (RSI, MACD, ATR, Lagged Returns)
    and drops all raw price variables and NaN samples.
    """
    df = df.copy()
    
    # 1. Construct Target
    # 1 if NEXT day's close > NEXT day's open, properly shifted.
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

def main():
    print("Loading data from data/nifty50_1d_yf.parquet...")
    df = pd.read_parquet("data/nifty50_1d_yf.parquet")
    print(f"Loaded DataFrame with shape: {df.shape}")
    
    print("Calculating features and target...")
    df_features = calculate_features(df)
    
    print(f"Feature set final shape: {df_features.shape}")
    print(f"Features: {list(df_features.columns.drop('target'))}")
    
    X = df_features.drop(columns=['target'])
    y = df_features['target']
    
    print("\nModel Setup: XGBClassifier")
    model = XGBClassifier(
        max_depth=3,
        n_estimators=200,
        learning_rate=0.01,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42, # reproducibility
        eval_metric='logloss'
    )
    
    print("Validating model with TimeSeriesSplit (n_splits=5)...")
    tscv = TimeSeriesSplit(n_splits=5)
    
    fold = 1
    accuracies = []
    
    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        
        # Fit model on training slice
        model.fit(X_train, y_train)
        
        # Predict validation slice
        preds = model.predict(X_test)
        
        # Check accuracy
        acc = accuracy_score(y_test, preds)
        accuracies.append(acc)
        print(f"Fold {fold} Accuracy: {acc:.4f}")
        fold += 1
        
    print(f"-> Mean Validation Accuracy: {np.mean(accuracies):.4f}")
    
    print("\nTraining final model on complete dataset...")
    model.fit(X, y)
    
    save_path = "nifty_daily_model.joblib"
    joblib.dump(model, save_path)
    print(f"Saved completed model to {save_path}")

if __name__ == "__main__":
    main()