import pandas as pd
import numpy as np
import pandas_ta as ta

def supertrend(df, period=10, multiplier=3.0):
    """
    Institutional Supertrend indicator.
    Returns a DataFrame with 'SUPERT', 'SUPERTd', 'SUPERTl', 'SUPERTs' columns.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Ensure columns are lowercase for pandas-ta
    df_copy = df.copy()
    df_copy.columns = [c.lower() for c in df_copy.columns]
    
    sti = ta.supertrend(df_copy['high'], df_copy['low'], df_copy['close'], length=period, multiplier=multiplier)
    return sti

def session_vwap(df):
    """
    Session-aware VWAP that resets at the start of each day.
    Critical for Indian Intraday (MIS) trading.
    """
    if df is None or df.empty:
        return pd.Series()
    
    df_copy = df.copy()
    # Support both 'Price'/'Volume' and 'Close'/'Volume'
    close_col = 'close' if 'close' in df_copy.columns else ('Close' if 'Close' in df_copy.columns else None)
    vol_col = 'volume' if 'volume' in df_copy.columns else ('Volume' if 'Volume' in df_copy.columns else None)
    
    if close_col is None or vol_col is None:
        return pd.Series()

    # Calculate VWAP
    pv = df_copy[close_col] * df_copy[vol_col]
    
    # Reset cumsum and volume sum daily
    groups = df_copy.index.date
    cum_pv = pv.groupby(groups).cumsum()
    cum_vol = df_copy[vol_col].groupby(groups).cumsum()
    
    vwap = cum_pv / cum_vol
    return vwap

def volume_profile(df, bins=20):
    """
    Basic Volume Profile implementation for identifying Value Areas.
    """
    if df is None or df.empty:
        return pd.DataFrame()
        
    close_col = 'close' if 'close' in df.columns else ('Close' if 'Close' in df.columns else None)
    vol_col = 'volume' if 'volume' in df.columns else ('Volume' if 'Volume' in df.columns else None)
    
    if close_col is None or vol_col is None:
        return pd.DataFrame()
        
    price_min = df[close_col].min()
    price_max = df[close_col].max()
    
    if price_min == price_max:
        return pd.DataFrame({'price': [price_min], 'volume': [df[vol_col].sum()]})
        
    bin_size = (price_max - price_min) / bins
    df['bin'] = ((df[close_col] - price_min) / bin_size).astype(int).clip(0, bins - 1)
    
    profile = df.groupby('bin').agg({
        vol_col: 'sum'
    }).reset_index()
    
    profile['price'] = price_min + (profile['bin'] * bin_size)
    return profile[['price', vol_col]]
