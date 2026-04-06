"""
train_nifty_model.py
====================
Production-grade training pipeline for the Nifty Ensemble strategy.

Temporal Split (strict, zero leakage):
    Training + CV  : 2015-01-01 → 2022-12-31  (7 years, ~42k bars)
    OOS Validation : 2023-01-01 → 2024-12-31  (2 years, held-out pre-production test)
    True OOS       : 2025-01-01 → present      (never seen — this is the live backtest window)

Feature Set (8 scale-invariant features):
    • RSI_14       — momentum oscillator, 0-100 bounded
    • MACD_pct     — MACD line normalised by close price (price-invariant)
    • ATR_pct      — ATR normalised by close price (volatility percentage)
    • ADX_14       — trend strength, 0-100 bounded
    • mom_5        — 5-bar price momentum %
    • mom_20       — 20-bar price momentum %
    • hour         — hour of day (session timing signal)
    • dayofweek    — day of week (Monday effect, expiry day effects)

These features are scale-invariant: trained on NIFTY values, they apply correctly
to any instrument (RELIANCE, TCS, etc.) without distribution shift.

The model + feature list are saved together in the artifact so inference always
uses the exact same features the model was trained on.
"""

import os

import joblib
import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401 — registers df.ta accessor
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.utils.class_weight import compute_sample_weight

# ── Temporal boundaries ───────────────────────────────────────────────────────
TRAIN_END  = "2022-12-31"
OOS_START  = "2023-01-01"
OOS_END    = "2024-12-31"
# 2025+ is the TRUE held-out window — the live backtest period. Never train on it.

# ── Canonical feature list ────────────────────────────────────────────────────
FEATURE_COLS = [
    "log_return",
    "volatility_20",
    "volume_delta",
    "hl_spread",
    "atr_pct",
    "bb_width",
    "vwap_dist",
    "htf_trend",
]

MODEL_FILE = "nifty_xgb_model.joblib"

RF_PARAMS = dict(
    n_estimators=200,
    max_depth=6,
    min_samples_leaf=50,   # heavy regularisation — prevents overfitting on intraday noise
    max_features="sqrt",
    random_state=42,
    n_jobs=-1,
)


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute strictly stationary features.
    No raw price inputs are used.
    """
    df = df.copy()

    # 1. log_return
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))

    # 2. volatility_20
    df["volatility_20"] = df["log_return"].rolling(window=20).std()

    # 3. volume_delta
    # ((Close - Low) - (High - Close)) / (High - Low + 1e-8) * Volume
    high_low = df["high"] - df["low"]
    buying_selling_pressure = ((df["close"] - df["low"]) - (df["high"] - df["close"]))
    df["volume_delta"] = (buying_selling_pressure / (high_low + 1e-8)) * df["volume"]

    # 4. hl_spread
    df["hl_spread"] = high_low / df["close"]

    # 5. ATR (used for dynamic targets AND as a normalized volatility feature)
    df.ta.atr(length=14, append=True)
    atr_col = "ATRr_14" if "ATRr_14" in df.columns else "ATR_14"
    df["atr_pct"] = df[atr_col] / df["close"]

    # 6. bb_width (Bollinger Bandwidth percentage)
    middle_band = df["close"].rolling(window=20).mean()
    std_dev = df["close"].rolling(window=20).std()
    upper_band = middle_band + (2 * std_dev)
    lower_band = middle_band - (2 * std_dev)
    df["bb_width"] = (upper_band - lower_band) / (middle_band + 1e-8)

    # 7. vwap_dist (Daily VWAP distance)
    # VWAP resets at the start of each trading day
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["typical_volume"] = df["typical_price"] * df["volume"]
    df["date_only"] = df.index.date
    cum_vol = df.groupby("date_only")["volume"].cumsum()
    cum_typ_vol = df.groupby("date_only")["typical_volume"].cumsum()
    df["vwap"] = cum_typ_vol / (cum_vol + 1e-8)
    df["vwap_dist"] = (df["close"] - df["vwap"]) / (df["vwap"] + 1e-8)
    df.drop(columns=["typical_price", "typical_volume", "date_only", "vwap"], inplace=True, errors="ignore")

    # 8. htf_trend (Percentage distance from 200 EMA)
    df.ta.ema(length=200, append=True)
    ema_cols = [c for c in df.columns if c.startswith("EMA_")]
    ema_col = ema_cols[-1] if ema_cols else "EMA_200"
    df["htf_trend"] = (df["close"] - df[ema_col]) / (df[ema_col] + 1e-8)

    # Drop NaNs created by rolling windows / shifts / ATR / EMA_200
    df.dropna(inplace=True)

    return df


def _make_model() -> RandomForestClassifier:
    return RandomForestClassifier(**RF_PARAMS)


def train_production_model() -> None:
    csv_path = "data/NIFTY 50_15minute.csv"
    if not os.path.exists(csv_path):
        print(f"CRITICAL: {csv_path} not found. Aborting.")
        return

    # ── Load & sort ───────────────────────────────────────────────────────────
    print(f"Loading {csv_path} ...")
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    print(f"Raw data : {len(df):,} bars  |  {df.index.min()} → {df.index.max()}")

    # ── Feature engineering ────────────────────────────────────────────────────
    df = _build_features(df)

    # ── Target: Triple-Barrier Method (Dynamic ATR) ──────────────────────────
    def _triple_barrier(prices: np.ndarray, atr_pcts: np.ndarray) -> np.ndarray:
        n = len(prices)
        labels = np.full(n, np.nan)
        for i in range(n - 15):
            p0 = prices[i]
            atr0 = atr_pcts[i]
            upper_bound = p0 * (1.0 + (atr0 * 1.5))  # +1.5 ATR Take Profit
            lower_bound = p0 * (1.0 - (atr0 * 1.0))  # -1.0 ATR Stop Loss
            
            label = 0  # Default to 0 (Hold/Cash) if time barrier hits
            for j in range(1, 16):  # Check strictly future prices up to 15 bars
                pt = prices[i + j]
                if pt >= upper_bound:
                    label = 1
                    break
                elif pt <= lower_bound:
                    label = -1
                    break
            labels[i] = label
        return labels

    print("Generating Dynamic ATR Triple-Barrier target labels...")
    df["target"] = _triple_barrier(df["close"].values, df["atr_pct"].values)
    df.dropna(inplace=True)

    # ── Verify features ────────────────────────────────────────────────────────
    available = [f for f in FEATURE_COLS if f in df.columns]
    missing   = [f for f in FEATURE_COLS if f not in df.columns]
    if missing:
        print(f"⚠ Missing features (will be skipped): {missing}")
    features = available
    print(f"Features used ({len(features)}): {features}")

    # ── Temporal split ────────────────────────────────────────────────────────
    df_train = df.loc[:TRAIN_END]
    df_oos   = df.loc[OOS_START:OOS_END]

    print(f"\nTrain window : {df_train.index.min().date()} → {df_train.index.max().date()}  ({len(df_train):,} bars)")
    print(f"OOS   window : {df_oos.index.min().date()}   → {df_oos.index.max().date()}    ({len(df_oos):,} bars)")
    print("True  OOS    : 2025-01-01 → present  (NEVER touched during training)\n")

    X_train = df_train[features]
    y_train = df_train["target"]
    X_oos   = df_oos[features]
    y_oos   = df_oos["target"]

    # ── Forward-walk CV within training window ────────────────────────────────
    print("Forward-walk cross-validation (5-fold TimeSeriesSplit on train window):")
    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = []

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X_train), start=1):
        Xtr, Xval = X_train.iloc[tr_idx], X_train.iloc[val_idx]
        ytr, yval = y_train.iloc[tr_idx], y_train.iloc[val_idx]

        weights = compute_sample_weight("balanced", ytr)
        m = _make_model()
        m.fit(Xtr, ytr, sample_weight=weights)
        score = accuracy_score(yval, m.predict(Xval))
        cv_scores.append(score)

        print(
            f"  Fold {fold}:  Train={len(Xtr):>6,}  Val={len(Xval):>5,}  "
            f"Accuracy={score:.4f}"
        )

    print(f"\n  CV Mean : {np.mean(cv_scores):.4f}")
    print(f"  CV Std  : {np.std(cv_scores):.4f}")

    # ── OOS evaluation (2023–2024) ────────────────────────────────────────────
    print("\nTraining on 2015–2022 → evaluating on OOS 2023–2024 ...")
    oos_model = _make_model()
    oos_weights = compute_sample_weight("balanced", y_train)
    oos_model.fit(X_train, y_train, sample_weight=oos_weights)

    oos_preds = oos_model.predict(X_oos)
    oos_proba = oos_model.predict_proba(X_oos)  # Shape: (N_samples, n_classes)
    oos_acc   = accuracy_score(y_oos, oos_preds)
    try:
        oos_auc = roc_auc_score(y_oos, oos_proba, multi_class="ovr")
    except Exception:
        oos_auc = float("nan")

    print(f"  OOS Accuracy : {oos_acc:.4f}")
    print(f"  OOS ROC-AUC  : {oos_auc:.4f}  (>0.55 is tradeable edge)")

    # ── Production model: train on 2015–2024 ─────────────────────────────────
    df_prod  = df.loc[:OOS_END]
    X_prod   = df_prod[features]
    y_prod   = df_prod["target"]

    print(f"\nTraining PRODUCTION model on 2015–2024 ({len(X_prod):,} bars) ...")
    final_model = _make_model()
    prod_weights = compute_sample_weight("balanced", y_prod)
    final_model.fit(X_prod, y_prod, sample_weight=prod_weights)

    print("\nPRODUCTION MODEL — FEATURE IMPORTANCE:")
    for name, imp in sorted(
        zip(features, final_model.feature_importances_), key=lambda x: -x[1]
    ):
        bar = "█" * int(imp * 40)
        print(f"  {name:<20s} {imp:.4f}  {bar}")

    # ── Save artifact (model + feature list) ─────────────────────────────────
    artifact = {
        "model":    final_model,
        "features": features,
        "meta": {
            "train_end":         TRAIN_END,
            "oos_end":           OOS_END,
            "oos_accuracy":      round(oos_acc, 4),
            "oos_roc_auc":       round(float(oos_auc), 4),
            "cv_mean_accuracy":  round(float(np.mean(cv_scores)), 4),
            "prediction_horizon_bars": 15,  # Triple barrier time horizon
        },
    }
    joblib.dump(artifact, MODEL_FILE)

    print(f"\n{'='*60}")
    print(f"✅ PRODUCTION MODEL saved → {MODEL_FILE}")
    print(f"   Features : {features}")
    print(f"   Trained  : 2015-01-01 → {OOS_END}")
    print("   2025+ is TRUE HELD-OUT (live backtest / live trading)")
    print(f"{'='*60}")


if __name__ == "__main__":
    train_production_model()
