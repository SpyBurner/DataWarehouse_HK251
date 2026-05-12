# BTL DW vs Steam-anomaly-detection — Diff Analysis

> **Purpose:** Identify every difference between the original Python-only pipeline (`Steam-anomaly-detection`) and the Pentaho ETL adaptation (`BTL DW`), focusing on why the `feature_matrix.csv` outputs differ.

---

## 1. Architecture Overview

| Aspect | Steam-anomaly-detection (Original) | BTL DW (Pentaho Adaptation) |
|--------|------------------------------------|-----------------------------|
| **Data source** | CSV files → `src/data_prep.py` → Parquet | CSV → Pentaho → MSSQL Staging → Postgres DW → SQL queries in `main.py` |
| **Data prep** | `src/data_prep.py` (Python) | Pentaho ETL jobs/transforms (`.kjb`/`.ktr` files) |
| **ML pipeline** | `main.py` → `src/*.py` | `ML_analytics/main.py` → `ML_analytics/src/*.py` |
| **Data loading in ML** | `load_parquets()` — reads `.parquet` files | `load_data_from_db()` — SQL queries against Postgres DW |
| **Infrastructure** | Standalone Python | Docker Compose: MSSQL + Postgres + Steam Crawler + ML Pipeline + Streamlit + LaTeX |

---

## 2. ETL Path Comparison

### Original: Python-only (`src/data_prep.py`)

```
data/raw/*.csv
  → _merge_with_crawled() (append crawled data in RAM)
  → Filter private_steamids
  → Parse/typecast
  → Deduplicate
  → data/processed/*.parquet
```

### BTL DW: Pentaho ETL → Postgres DW

```
Datasets/landing/extract_dt=.../
  → [00_validate_landing.kjb]     Find newest unprocessed partition
  → [10_load_mssql_staging_*.ktr] CSV → MSSQL stg_* tables (5 parallel transforms)
  → [20_build_postgres_dw_*.ktr]  MSSQL stg → Postgres dw.* (4 sequential transforms)
  → [30_build_datamart_features.ktr] DW joins → dm.dm_steam_player_features_v1
  → [Write audit log → dbo.stg_load_audit]
```

### Key Differences in ETL

| Step | Original Python | BTL DW Pentaho |
|------|----------------|----------------|
| **CSV loading** | `pd.read_csv()` with explicit dtypes | Pentaho "CSV file input" steps → MSSQL staging (all `NVARCHAR(MAX)`) |
| **Crawled data merge** | `_merge_with_crawled()` — concat in RAM | Separate crawler container drops new CSVs into `Datasets/landing/` partitions |
| **Private ID filtering** | Python: `df[~df["playerid"].isin(private_ids)]` | Pentaho: `stg_private_steamids` loaded → Postgres `dim_player.is_private = TRUE` → SQL `WHERE p.is_private = FALSE` |
| **Library JSON parsing** | `_parse_list_fast()` in Python | Pentaho: `20_build_postgres_dw_fact_library.ktr` explodes the JSON list into individual `(playerid, appid, playtime_mins)` rows |
| **Deduplication** | `drop_duplicates(keep="last")` | Postgres triggers with `ON CONFLICT` / `BEFORE INSERT` checks |
| **Type casting** | `pd.to_datetime()`, `.astype("Int32")` | SQL casts in Pentaho transforms + Postgres column types |
| **Date typo handling** | `date_accquired` → `date_acquired` column merge | Pentaho transforms may or may not handle this (depends on CSV headers in landing data) |

---

## 3. ML Pipeline Code Differences

### 3.1 `main.py` — Data Loading

This is the **primary structural difference** — the source of data changes completely.

#### Original (`Steam-anomaly-detection/main.py`)

```python
def load_parquets() -> tuple:
    history   = pd.read_parquet("data/processed/history.parquet")
    players   = pd.read_parquet("data/processed/players.parquet")
    reviews   = pd.read_parquet("data/processed/reviews.parquet")
    purchased = pd.read_parquet("data/processed/purchased.parquet")
    return history, players, reviews, purchased
```

#### BTL DW (`ML_analytics/main.py`)

```python
def load_data_from_db() -> tuple:
    engine = create_engine(conn_str)  # PostgreSQL connection
    
    history = pd.read_sql("""
        SELECT h.playerid, h.achievementid, h.date_acquired
        FROM dw.fact_achievement_unlock h
        JOIN dw.dim_player p ON h.playerid = p.playerid
        WHERE p.is_private = FALSE
    """, engine)
    
    # ... similar SQL for players, reviews, purchased
    
    purchased = pd.read_sql("""
        SELECT l.playerid, 
               json_agg(json_build_object('appid', l.appid, 'playtime_mins', l.playtime_mins))::text AS library
        FROM dw.fact_library l
        JOIN dw.dim_player p ON l.playerid = p.playerid
        WHERE p.is_private = FALSE
        GROUP BY l.playerid
    """, engine)
```

### 3.2 `src/features.py`

The BTL DW version has **10 additional lines** (575 lines vs 565 lines in the original). The differences are:

- **Lines 416–424 (BTL DW only):** A commented-out block for handling empty reviews DataFrames. This is dead code (wrapped in `# if reviews.empty:` comments) and has no runtime effect.
  
**All feature computation logic is otherwise identical.**

### 3.3 `src/models.py`

**Byte-for-byte identical** between both repos (23,011 bytes each).

### 3.4 `src/data_prep.py`

**Byte-for-byte identical** between both repos (10,546 bytes each). This file exists in BTL DW but is **not used** — BTL DW loads from the database directly.

### 3.5 `src/evaluate.py`

**Byte-for-byte identical** (12,639 bytes each).

### 3.6 `src/active_learning.py`

**Byte-for-byte identical** (7,249 bytes each).

---

## 4. Data Schema Differences (Root Causes of Feature Matrix Divergence)

### 4.1 Postgres DW Schema vs Original CSV Structure

| Table | Original CSV | Postgres DW (`dw.*`) | Potential Impact |
|-------|-------------|---------------------|-----------------|
| **history** | `playerid` (int64), `achievementid` (string), `date_acquired` (datetime) | `playerid` (VARCHAR(30)), `achievementid` (TEXT), `date_acquired` (TIMESTAMP). PK = `(playerid, achievementid)` — **no `date_acquired` in PK** | DW deduplicates on `(playerid, achievementid)` only, while original deduplicates on `(playerid, achievementid, date_acquired)`. If a player unlocks the same achievement at different times (re-unlock), **DW keeps only one row, original keeps both.** |
| **reviews** | `reviewid` (int32), all numeric IDs | `reviewid` (VARCHAR(30)), `playerid` (VARCHAR(30)), `gameid` (VARCHAR(30)) | ID type mismatch: Python ML code casts `playerid` to `int64` after loading from DB. Postgres stores as string → may introduce subtle sorting/groupby differences |
| **library** | `purchased_games.csv`: `playerid`, `library` (JSON string) | `dw.fact_library`: normalized to `(playerid, appid, playtime_mins)` — one row per game | The DB query re-aggregates: `json_agg(json_build_object('appid', l.appid, 'playtime_mins', l.playtime_mins))`. The resulting JSON structure should be equivalent, but the **order of games** may differ. |
| **players** | `country` (category dtype) | `country` (VARCHAR(50)) | No functional difference |

### 4.2 Referential Integrity Filtering (DW ONLY)

The Postgres DW has **foreign key triggers** that silently drop rows:

```sql
-- fact_achievement_unlock trigger:
-- Rejects rows where playerid NOT IN dim_player
-- Rejects rows where achievementid NOT IN fact_achievement

-- fact_library trigger:
-- Rejects rows where playerid NOT IN dim_player  
-- Rejects rows where appid NOT IN dim_game
```

**This means:** If a game in a player's library doesn't exist in `dim_game`, that `(playerid, appid)` row is **silently dropped** from `fact_library`. In the original pipeline, the game would simply appear in the library list (no referential check). This can cause:
- **Different `library_size` values** → impacts `achievement_game_ratio`, trimming decisions
- **Different `playtime_mins` availability** → impacts `zero_playtime_achievements_ratio`, `total_playtime_mins`, `playtime_per_achievement`
- **Different `review_unplayed_ratio`** → if a game is dropped from the library, reviews for that game are no longer counted as "unplayed"

### 4.3 Achievement ID filtering (DW ONLY)

```sql
-- fact_achievement_unlock requires achievementid IN fact_achievement
```

If `fact_achievement` (the dimension table loaded from `achievements.csv`) doesn't contain an achievement that a player unlocked, **that unlock event is silently dropped** from `fact_achievement_unlock`. The original pipeline has no such filter — all achievement events are kept regardless of whether the achievement is in a reference table.

**Impact:** Fewer achievement records → different `total_achievements`, `median_unlock_interval_sec`, `max_achievements_per_day`, etc.

---

## 5. Specific Root Causes of Feature Matrix Differences

Based on the analysis above, here are the most likely causes of differing `feature_matrix.csv` outputs:

### 🔴 HIGH IMPACT

#### 5.1 Achievement Row Count Difference
- **Cause:** DW's `fact_achievement_unlock` trigger rejects rows where `achievementid` is not in `fact_achievement`. The original pipeline keeps all rows.
- **Affected features:** ALL speed features (median/std interval, CV, max/min/day), ALL temporal features (night ratio, entropy, density), ALL diversity features (total_achievements, concentration metrics, HHI), playtime features
- **How to verify:** Compare `SELECT COUNT(*) FROM dw.fact_achievement_unlock` against the row count in `history.parquet`

#### 5.2 Library Row Count Difference
- **Cause:** DW's `fact_library` trigger rejects rows where `appid` is not in `dim_game`. The original pipeline keeps all library entries.
- **Affected features:** `library_size`, `achievement_game_ratio`, `zero_playtime_achievements_ratio`, `total_playtime_mins`, `playtime_per_achievement`, `review_unplayed_ratio`
- **How to verify:** Compare the total number of distinct `(playerid, appid)` pairs in `fact_library` vs the original `purchased_games.csv` parsed library

#### 5.3 Deduplication Scope Difference
- **Cause:** DW uses PK `(playerid, achievementid)` — ignoring `date_acquired`. Original uses `(playerid, achievementid, date_acquired)`.
- **Impact:** If a player has the same achievement recorded at two different timestamps, DW keeps one, original keeps both. This changes interval calculations.
- **Affected features:** ALL speed and temporal features

### 🟡 MEDIUM IMPACT

#### 5.4 Player Inclusion/Exclusion Differences
- **Cause:** Private player filtering mechanisms differ:
  - Original: `playerid ∈ private_steamids.csv` → removed during data_prep
  - DW: `dim_player.is_private = TRUE` → filtered via SQL `WHERE p.is_private = FALSE`
  - The DW approach depends on the Pentaho transform `20_build_postgres_dw_dim_private_steamid.ktr` correctly marking players as private
- **Impact:** Different player populations → different trimming results → different feature matrix rows

#### 5.5 Review Row Differences
- **Cause:** DW's `fact_review` trigger rejects rows where `playerid NOT IN dim_player` or `gameid NOT IN dim_game`
- **Impact:** Missing reviews → different `total_reviews`, `review_duplication_rate`, `avg_review_length`, `min_review_length`

### 🟢 LOW IMPACT

#### 5.6 Data Type Precision
- **Cause:** Postgres stores `playerid` as VARCHAR(30), Python as int64. Conversions may introduce subtle differences.
- **Impact:** Unlikely to cause feature value differences, but may affect join/sort determinism

#### 5.7 Crawled Data Merge
- **Cause:** Original merges `data/crawled/*.csv` in-memory. BTL DW relies on the crawler depositing new data into `Datasets/landing/` partitions processed by Pentaho.
- **Impact:** If crawled data was included in one pipeline but not the other, the input data sets differ from the start.

---

## 6. Datamart Status

The `SQL_Postgres_InitWarehouse copy.sql` file contains a `dm` (datamart) schema with table `dm.dm_steam_player_features_v1` (25 feature columns). There's also a Pentaho transform `30_build_datamart_features.ktr` that computes features via SQL joins.

However, per user's note: **the Datamart idea is scrapped.** The current pipeline in BTL DW uses `ML_analytics/main.py` which queries the DW directly and computes features in Python (via `features.py`), **bypassing the SQL-based datamart entirely.**

The `30_build_datamart_features.ktr` and `dm.*` schema tables exist but are **not used** by the ML pipeline.

### Pentaho Datamart vs Python Feature Engineering

If the datamart were used, there would be additional differences:
- **Shannon entropy:** Computed via PostgreSQL function `dw.calculate_shannon_entropy()` using natural log (`ln`), matching `scipy.stats.entropy` (which also uses `ln` by default)
- **`review_duplication_rate`:** Pentaho README notes this is "currently a placeholder (= 0)" in the datamart
- **Timezone adjustment:** Would use `dw.dim_country_utc_offset` table rather than the Python `_COUNTRY_UTC_OFFSET` dict (same values, but DB query vs in-memory lookup)

---

## 7. Verification Checklist

To track down the exact cause of feature_matrix differences, run these checks:

- [ ] **Row counts:** Compare total rows in each table between DW and original parquets
  ```sql
  SELECT 'history' AS tbl, COUNT(*) FROM dw.fact_achievement_unlock
  UNION ALL
  SELECT 'players', COUNT(*) FROM dw.dim_player WHERE is_private = FALSE
  UNION ALL
  SELECT 'reviews', COUNT(*) FROM dw.fact_review
  UNION ALL
  SELECT 'library', COUNT(*) FROM dw.fact_library;
  ```
- [ ] **Player set:** Compare the set of `playerid` values in both feature matrices — find IDs present in one but not the other
- [ ] **Per-feature comparison:** For players present in both, compute `abs(value_original - value_btl)` per feature and sort by magnitude
- [ ] **Specific achievement check:** Pick a player with large differences and manually count their achievements in both data sources
- [ ] **Library check:** For the same player, compare their library size and game list between both sources
- [ ] **FK rejection audit:** Check how many rows were rejected by the DW triggers (look at insert counts vs expected counts in the Pentaho logs at `Pentaho/jobs/overnight.log`)

---

## 8. Summary of Files Compared

| File | Original | BTL DW | Status |
|------|----------|--------|--------|
| `src/data_prep.py` | ✅ | ✅ (unused — ML reads from DB) | **Identical** |
| `src/features.py` | 565 lines | 575 lines | **Near-identical** — BTL DW has 10 lines of commented-out dead code |
| `src/models.py` | 531 lines | 531 lines | **Identical** |
| `src/evaluate.py` | 287 lines | 287 lines | **Identical** |
| `src/active_learning.py` | 191 lines | 191 lines | **Identical** |
| `main.py` | 202 lines | 275 lines | **Different** — BTL DW replaces `load_parquets()` with `load_data_from_db()` (SQL queries + library JSON parsing) |
| `batch_analysis.py` | ✅ | ✅ | **Identical** |
| `streamlit_app.py` | 88,710 bytes | 91,936 bytes | **Different** — BTL DW version likely has DB-aware changes |
| `run_testcase_evaluation.py` | ✅ | ✅ | **Identical** |

### Conclusion

The ML pipeline code (feature engineering, model training, evaluation) is **virtually identical** between the two repos. The **only meaningful code change** is in `main.py`'s data loading function, which switches from parquet files to PostgreSQL queries.

The **feature matrix differences are NOT caused by different ML code** — they are caused by **different input data** reaching the ML pipeline, due to:
1. DW foreign key triggers silently dropping rows (achievements, library entries, reviews)
2. Different deduplication PK scope (DW ignores `date_acquired` in achievement dedup)
3. Potentially different player inclusion based on how private ID filtering is implemented
