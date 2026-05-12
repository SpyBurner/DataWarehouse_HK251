import pandas as pd
import os
import numpy as np

# Configuration
PATH_BTL = r'd:\GeneralProjectSpace\.UNI\.HKVIII\Datawarehouse\BTL DW\ML_analytics\outputs\feature_matrix.csv'
PATH_ORIGINAL = r'd:\GeneralProjectSpace\.UNI\.HKVIII\Datawarehouse\Steam-anomaly-detection\outputs\feature_matrix.csv'

def check_diffs():
    print("=== Steam Feature Matrix Diff Checker ===")
    
    # 1. Load files
    if not os.path.exists(PATH_BTL):
        print(f"Error: BTL file not found at {PATH_BTL}")
        return
    if not os.path.exists(PATH_ORIGINAL):
        print(f"Error: Original file not found at {PATH_ORIGINAL}")
        return

    print("Loading datasets...")
    df_btl = pd.read_csv(PATH_BTL)
    df_orig = pd.read_csv(PATH_ORIGINAL)

    # 2. Set index to playerid
    if 'playerid' not in df_btl.columns or 'playerid' not in df_orig.columns:
        print("Error: 'playerid' column missing in one of the files.")
        return

    df_btl = df_btl.set_index('playerid')
    df_orig = df_orig.set_index('playerid')

    # 3. Find common players
    common_ids = df_btl.index.intersection(df_orig.index)
    print(f"Total players in BTL: {len(df_btl)}")
    print(f"Total players in Original: {len(df_orig)}")
    print(f"Common players found: {len(common_ids)}")
    
    if len(common_ids) == 0:
        print("No common players to compare.")
        return

    # 4. Filter to common players and columns
    df_btl_c = df_btl.loc[common_ids]
    df_orig_c = df_orig.loc[common_ids]
    
    common_cols = df_btl_c.columns.intersection(df_orig_c.columns)
    print(f"Common features found: {len(common_cols)}")

    # 5. Compare column by column
    diff_results = []
    
    for col in common_cols:
        # Check for numeric differences with a small tolerance for floating point noise
        if pd.api.types.is_numeric_dtype(df_btl_c[col]) and pd.api.types.is_numeric_dtype(df_orig_c[col]):
            # Fill NaNs with a unique value to treat NaN vs NaN as match and NaN vs value as diff
            v1 = df_btl_c[col].fillna(-999999)
            v2 = df_orig_c[col].fillna(-999999)
            # Use np.isclose for floats, otherwise !=
            is_diff = ~np.isclose(v1, v2, rtol=1e-05, atol=1e-08)
        else:
            is_diff = (df_btl_c[col].fillna('NAN') != df_orig_c[col].fillna('NAN'))
        
        diff_count = is_diff.sum()
        diff_results.append({
            'Feature': col,
            'Diff Count': diff_count,
            'Diff %': (diff_count / len(common_ids)) * 100
        })

    # 6. Sort and display
    results_df = pd.DataFrame(diff_results).sort_values(by='Diff Count', ascending=False)
    
    print("\n--- Feature Discrepancy Summary (Ordered by Most Differences) ---")
    print(results_df.to_string(index=False))
    
    # Save to CSV for further analysis
    out_path = 'feature_diff_summary.csv'
    results_df.to_csv(out_path, index=False)
    print(f"\nResults saved to {os.path.abspath(out_path)}")

if __name__ == "__main__":
    check_diffs()
