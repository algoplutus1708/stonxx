import pandas as pd
import sys
import os
import glob

# 1. Automatically find all .parquet files in the data folder
list_of_files = glob.glob('data/*.parquet')

# 2. Check if the folder is empty
if not list_of_files:
    print("\n[CRITICAL ERROR] No .parquet files found in the 'data/' directory!")
    print("This means dhan_historical_fetcher.py failed silently and downloaded absolutely nothing.")
    print("Check your API permissions and network connection.")
    sys.exit(1)

# 3. Grab the newest file automatically
FILE_PATH = max(list_of_files, key=os.path.getctime)
print(f"\n[SUCCESS] Found data file: {FILE_PATH}")

# 4. Read and verify the data
try:
    df = pd.read_parquet(FILE_PATH)
    
    print("\n--- DATAFRAME INFO ---")
    df.info()
    
    print("\n--- FIRST 5 CANDLES ---")
    print(df.head())
    
    print("\n--- LAST 5 CANDLES ---")
    print(df.tail())
    
except Exception as e:
    print(f"\n[ERROR] Failed to read parquet file: {e}")
    sys.exit(1)