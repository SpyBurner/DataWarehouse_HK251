# Feature Matrix Diff — Root Cause Analysis & Debugging Guide

> **Context:** Both repos (`Steam-anomaly-detection` and `BTL DW`) use the **same `features.py`** code. The feature_matrix differences are caused entirely by **different input data** reaching the ML pipeline. This guide breaks down each discrepancy tier and tells you exactly how to fix it.

---

## Diff Summary (from `DiffChecker/feature_diff_summary.csv`)

| Tier | Feature | Diff Count | Diff % |
|------|---------|-----------|--------|
| 🔴 T1 | `account_age_days` | 3,296 | 99.2% |
| 🔴 T1 | `library_size` | 3,275 | 98.6% |
| 🟠 T2 | `achievement_game_ratio` | 2,493 | 75.0% |
| 🟡 T3 | `avg_review_length` | 1,860 | 56.0% |
| 🟡 T3 | `total_playtime_mins` | 1,275 | 38.4% |
| 🟡 T3 | `playtime_per_achievement` | 1,275 | 38.4% |
| 🟡 T3 | `min_review_length` | 951 | 28.6% |
| 🔵 T4 | `review_unplayed_ratio` | 354 | 10.7% |
| 🔵 T4 | `zero_playtime_achievements_ratio` | 256 | 7.7% |
| ⚪ T5 | 9 features (speed, temporal, diversity) | 6 each | 0.18% |
| ⚪ T5 | `median_unlock_interval_sec` | 2 | 0.06% |
| ✅ OK | `max_achievements_per_minute/day`, `total_reviews`, `days_before_first_achievement` | 0 | 0% |

---

## 🔴 Tier 1: `account_age_days` — 99.2% differ

### Root Cause: Different `reference_time`

Both pipelines compute:
```python
account_age_days = (reference_time - player_created).dt.days
```

`reference_time` is set in `main.py` as **the max `date_acquired` in the history table**:
```python
feature_reference_time = pd.to_datetime(history["date_acquired"], errors="coerce").max()
```

The two pipelines ran at **different times** with potentially **different history data** (the DW may have slightly more/fewer achievement records due to FK filtering). So they computed **different `max(date_acquired)` values**, causing nearly every player's `account_age_days` to shift by a constant offset.

### How to verify
```python
# In BTL DW main.py, after loading:
print("BTL reference_time:", feature_reference_time)

# In Original main.py, after loading:
print("Original reference_time:", feature_reference_time)
```

### How to fix

**Option A (quick):** Force the same reference time in both pipelines. Add to `BTL DW/ML_analytics/main.py` after line 156:
```python
# Force reference time to match original pipeline
feature_reference_time = pd.Timestamp("2026-04-02 17:07:55")  # from original run
```

**Option B (proper):** This diff is **not a real data quality issue** — it's just a timestamp offset. If both pipelines used the same reference point, the values would match. You can accept this diff as expected.

### Priority: 🟢 LOW — cosmetic difference, does not affect model quality

---

## 🔴 Tier 1: `library_size` — 98.6% differ

### Root Cause: DW FK trigger drops library entries

This is the **most impactful** difference and the root cause of several downstream features.

#### What happens in the Original pipeline:
```
purchased_games.csv → _parse_list_fast() → library = [{appid: X, playtime_mins: Y}, ...]
library_size = len(library)  // ALL games in CSV are counted
```

#### What happens in the BTL DW pipeline:
```
purchased_games.csv → Pentaho → stg_purchased_games
                    → Pentaho explodes JSON → tries to INSERT into dw.fact_library
                    → FK trigger fires:
                        IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.appid)
                            THEN RETURN NULL;  // ← SILENTLY DROPS THE ROW
                    → Only games present in dim_game survive
                    → ML pipeline: SELECT ... FROM dw.fact_library → json_agg → library_size
```

**The DW requires every game to exist in `dim_game`.** If `games.csv` (loaded into `dim_game`) doesn't contain a game that a player owns, that library entry is silently dropped. The original pipeline has no such check.

### How to verify

Run these SQL queries on the DW:

```sql
-- 1. Count how many library entries survived FK filtering
SELECT COUNT(*) AS dw_library_entries FROM dw.fact_library;

-- 2. Count how many were in the raw staging data
SELECT SUM(json_array_length(library::json)) AS raw_library_entries
FROM dbo.stg_purchased_games;  -- run on MSSQL staging

-- 3. Find games owned by players but missing from dim_game
-- (These are the entries being silently dropped)
-- You'd need to check this at the Pentaho transform level
-- or compare the original CSV library contents against dim_game
```

Also, run this in the `DiffChecker/` directory to directly compare:
```python
import pandas as pd

btl = pd.read_csv(r'...\BTL DW\ML_analytics\outputs\feature_matrix.csv')
orig = pd.read_csv(r'...\Steam-anomaly-detection\outputs\feature_matrix.csv')

btl = btl.set_index('playerid')
orig = orig.set_index('playerid')

common = btl.index.intersection(orig.index)
diff = (orig.loc[common, 'library_size'] - btl.loc[common, 'library_size'])
print("Library size difference stats:")
print(diff.describe())
print(f"\nPlayers where Original > BTL: {(diff > 0).sum()}")
print(f"Players where BTL > Original: {(diff < 0).sum()}")
print(f"Players with exact match: {(diff == 0).sum()}")
```

If the result shows `Original > BTL` for nearly all players, it confirms the FK trigger is the cause.

### How to fix

**Option A (recommended — fix the DW):**
Ensure `dim_game` contains ALL game IDs that appear in any player's library, not just the games from `games.csv`. Add a pre-load step in the Pentaho pipeline that extracts distinct `appid` values from library data and inserts them into `dim_game` with placeholder metadata before loading `fact_library`.

```sql
-- Run BEFORE loading fact_library
-- Extract all unique appids from the staging library data and insert as dim_game stubs
INSERT INTO dw.dim_game (gameid, title, release_date)
SELECT DISTINCT appid, 'Unknown', NULL
FROM dw.stg_library_temp  -- or however your staging exposes the parsed appids
WHERE appid IS NOT NULL
ON CONFLICT (gameid) DO NOTHING;
```

**Option B (quick fix — remove the FK trigger):**
```sql
DROP TRIGGER trg_library_fk ON dw.fact_library;
ALTER TABLE dw.fact_library DROP CONSTRAINT fk_library_game;
```
This loses referential integrity but makes the data flow match the original.

**Option C (fix in the SQL query):**
If you can't change the DW schema, the ML pipeline could directly parse the library from the staging area instead of `fact_library`. But this defeats the purpose of having a DW.

### Priority: 🔴 CRITICAL — cascading impact on 6+ downstream features

---

## 🟠 Tier 2: `achievement_game_ratio` — 75% differ

### Root Cause: Derived from `library_size` (Tier 1 cascade)

```python
achievement_game_ratio = games_with_achievements / library_size.clip(lower=1)
```

Since `library_size` differs (Tier 1), the denominator changes → the ratio changes.

### How to fix: Fix `library_size` (Tier 1). This will auto-resolve.

---

## 🟡 Tier 3: `avg_review_length` / `min_review_length` — 56% / 29% differ

### Root Cause: Review text encoding/storage differences

The review `text` goes through two very different paths:

| Step | Original | BTL DW |
|------|----------|--------|
| Source | `reviews.csv` → `pd.read_csv(dtype={"review": "string"})` | `reviews.csv` → Pentaho CSV input → MSSQL `NVARCHAR(MAX)` → Postgres `TEXT` → `pd.read_sql()` |
| Encoding | UTF-8, read directly | UTF-8 → NVARCHAR(MAX) → TEXT (multiple encoding conversions) |
| Escaping | Raw CSV escaping preserved | Pentaho may re-escape special characters, add/strip whitespace, or truncate |

**Likely causes (in order of probability):**

1. **Whitespace handling:** MSSQL `NVARCHAR(MAX)` may pad or trim trailing whitespace differently than Python's CSV reader. `str.len()` counts whitespace, so even a single trailing space per review shifts the length.

2. **Encoding artifacts:** Non-ASCII characters (Chinese, Russian, emoji reviews) may be re-encoded through the MSSQL → Postgres pipeline, changing byte lengths.

3. **NULL vs empty string:** If the review column is `NULL` in Postgres but `""` in the CSV, `fillna("").str.len()` yields 0 vs the original value.

4. **Pentaho escaping:** Pentaho's CSV input may interpret embedded quotes, newlines, or commas differently than `pd.read_csv`, altering the review text.

### How to verify

Add this debug script:

```python
import pandas as pd

# Load from both sources
btl_reviews = pd.read_sql("SELECT reviewid, playerid, review FROM dw.fact_review", engine)
orig_reviews = pd.read_csv("reviews.csv", usecols=["reviewid", "playerid", "review"], dtype={"review": "string"})

# Compare review lengths for matching reviewids
btl_reviews["rlen"] = btl_reviews["review"].fillna("").str.len()
orig_reviews["rlen"] = orig_reviews["review"].fillna("").str.len()

merged = btl_reviews.merge(orig_reviews, on="reviewid", suffixes=("_btl", "_orig"))
merged["len_diff"] = merged["rlen_btl"] - merged["rlen_orig"]

print("Review length difference stats:")
print(merged["len_diff"].describe())
print(f"\nReviews with different length: {(merged['len_diff'] != 0).sum()}")

# Show sample mismatches
sample = merged[merged["len_diff"] != 0].head(5)
for _, row in sample.iterrows():
    print(f"\nReviewID: {row['reviewid']}")
    print(f"  Original: [{row['rlen_orig']}] {repr(row['review_orig'][:100])}")
    print(f"  BTL DW:   [{row['rlen_btl']}] {repr(row['review_btl'][:100])}")
```

### How to fix

Once you identify the pattern (trimming? encoding? escaping?), fix it in the Pentaho transform `10_load_mssql_staging_reviews.ktr` or `20_build_postgres_dw_fact_review.ktr`. Common fixes:

- **Whitespace:** Add a Pentaho "String operations" step to trim the review field
- **Encoding:** Ensure both Pentaho CSV input and MSSQL connection use UTF-8
- **NULL handling:** In the DW SQL query, use `COALESCE(r.review, '')` to match the original's behavior

### Priority: 🟡 MEDIUM — affects review bot heuristic (`avg_review_length < 50` threshold)

---

## 🟡 Tier 3: `total_playtime_mins` / `playtime_per_achievement` — 38.4% differ

### Root Cause: Cascade from `library_size` (Tier 1)

The playtime features join achievements against the library:
```python
hist_classified = hist_core.merge(lib_flat, on=["playerid", "gameid"], how="left")
# Only Condition B (playtime > 0) and C (playtime == 0) games in library contribute
```

If `fact_library` is missing games due to the FK trigger (Tier 1), the left join produces more `NaN` playtime values → the original "Condition B" games become "Condition A" (not in library) → they're excluded → different totals.

### How to fix: Fix `library_size` (Tier 1). This will auto-resolve.

---

## 🔵 Tier 4: `review_unplayed_ratio` — 10.7% differ

### Root Cause: Double cascade from library + review diffs

```python
review_unplayed_ratio = fraction of reviews for games where playtime_mins == 0
```

This uses the `zero_playtime_library` dict built from `purchased`. If the library is missing games (Tier 1), the zero-playtime game set changes → the ratio changes.

Additionally, if review text differences (Tier 3) caused any reviews to be lost during Pentaho ETL (e.g., reviews rejected by the FK trigger because `gameid NOT IN dim_game`), the denominator changes too.

### How to fix: Fix `library_size` (Tier 1) and review data (Tier 3). Partially auto-resolves.

---

## 🔵 Tier 4: `zero_playtime_achievements_ratio` — 7.7% differ

### Root Cause: Cascade from library (Tier 1)

```python
zero_playtime_achievements_ratio = C / (B + C)
```

If games are missing from `fact_library`, some "Condition C" (owned, zero playtime) or "Condition B" (owned, played) games become "Condition A" (not in library, excluded). This changes both numerator and denominator.

### How to fix: Fix `library_size` (Tier 1). This will auto-resolve.

---

## ⚪ Tier 5: 9 features with exactly 6 diffs (0.18%)

### Root Cause: 6 players with different achievement data

All history-derived features (`std_unlock_interval_sec`, `total_achievements`, `night_activity_ratio`, `hour_entropy`, `activity_density`, `cv_unlock_interval`, `top1/top3_game_concentration`, `game_hhi`, `avg_achievements_per_game`) differ for exactly **6 players**.

This is caused by the DW's `fact_achievement_unlock` FK trigger:
```sql
-- Rejects rows where achievementid NOT IN fact_achievement
IF NOT EXISTS (SELECT 1 FROM dw.fact_achievement WHERE achievementid = NEW.achievementid)
    THEN RETURN NULL;
```

For these 6 players, some of their achievement unlock records were dropped because the achievement wasn't in `fact_achievement` (loaded from `achievements.csv`).

### How to verify

```python
# Find the 6 players
import numpy as np
btl = pd.read_csv(BTL_PATH).set_index('playerid')
orig = pd.read_csv(ORIG_PATH).set_index('playerid')
common = btl.index.intersection(orig.index)

diff_mask = ~np.isclose(
    btl.loc[common, 'total_achievements'].fillna(-999999),
    orig.loc[common, 'total_achievements'].fillna(-999999)
)
problem_players = common[diff_mask]
print("Players with achievement count differences:", problem_players.tolist())
```

Then for each player:
```sql
-- Count in DW
SELECT COUNT(*) FROM dw.fact_achievement_unlock WHERE playerid = '<id>';

-- Count in original (from parquet or raw CSV)
-- Compare the counts
```

### How to fix

Same pattern as Tier 1: ensure `fact_achievement` contains ALL achievement IDs that appear in `history.csv`. Add a pre-load step:

```sql
-- Extract unique achievementids from staging history and insert stubs
INSERT INTO dw.fact_achievement (achievementid, gameid)
SELECT DISTINCT
    h.achievementid,
    COALESCE(NULLIF(split_part(h.achievementid, '_', 1), ''), '-1')
FROM dw_staging.stg_history h  -- or however your staging exposes this
WHERE h.achievementid IS NOT NULL
ON CONFLICT (achievementid) DO NOTHING;
```

### Priority: 🟢 LOW — only 6 players affected

---

## Summary: Fix Priority Order

```
┌─────────────────────────────────────────────────────────────┐
│  FIX #1: library_size (Tier 1)                              │
│  → Ensure dim_game has ALL game IDs before loading          │
│     fact_library                                            │
│  → Auto-fixes: achievement_game_ratio, total_playtime_mins, │
│     playtime_per_achievement, review_unplayed_ratio,         │
│     zero_playtime_achievements_ratio                         │
│  → Resolves ~98% + cascading fixes for 75%, 38%, 10%, 7%   │
├─────────────────────────────────────────────────────────────┤
│  FIX #2: account_age_days (Tier 1)                          │
│  → Force same reference_time or accept as expected diff     │
│  → Resolves 99.2%                                           │
├─────────────────────────────────────────────────────────────┤
│  FIX #3: avg/min_review_length (Tier 3)                     │
│  → Debug review text encoding in Pentaho pipeline           │
│  → Resolves 56% + 29%                                       │
├─────────────────────────────────────────────────────────────┤
│  FIX #4: achievement FK stubs (Tier 5)                      │
│  → Pre-load fact_achievement with all achievementids        │
│  → Resolves the 6-player diff across 9 features            │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Debugging Checklist

- [ ] Run the library size comparison script (see Tier 1 verify section)
- [ ] Check `dim_game` row count vs distinct appids in raw `purchased_games.csv`
- [ ] Compare `reference_time` values from both pipeline logs
- [ ] Run the review text comparison script (see Tier 3 verify section)
- [ ] Identify the 6 players with achievement diffs (see Tier 5 verify section)
- [ ] After fixing Tier 1, re-run both pipelines and re-run `DiffChecker/diff_features.py`
