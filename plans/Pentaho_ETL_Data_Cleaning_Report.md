# Pentaho ETL Pipeline — Data Cleaning & Processing Report

> **Scope:** This document describes the full Pentaho ETL process from raw CSV ingestion through to the PostgreSQL Data Warehouse, with a focus on every data cleaning, transformation, and integrity enforcement step.

---

## 1. Pipeline Architecture Overview

```
┌──────────────────────┐
│  Steam Crawler        │ → Drops CSVs into Datasets/landing/extract_dt=YYYYMMDD/
│  (Python/Docker)      │   Files: players.csv, history.csv, reviews.csv,
└────────┬─────────────┘   purchased_games.csv, private_steamids.csv,
         │                  achievements.csv, games.csv
         ▼
┌──────────────────────┐
│  Phase 00: VALIDATE   │ → Find newest unprocessed partition
│  (Pentaho Job)        │   Check required files exist
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│  Phase 05: RAW LOAD   │ → CSV → raw file read (9 transforms, optional preview)
│  (Pentaho Transforms) │
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│  Phase 10: STAGING    │ → CSV → MSSQL DW_Staging (5 transforms, parallel)
│  (Pentaho Transforms) │   Tables: dbo.stg_players, stg_history, stg_reviews,
└────────┬─────────────┘   stg_purchased_games, stg_private_steamids
         ▼
┌──────────────────────┐
│  Phase 20: DW BUILD   │ → MSSQL staging → Postgres DW (sequential)
│  (Pentaho Transforms) │   Dims first, then facts
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│  Postgres DW          │ → Star schema: dw.dim_player, dw.dim_game,
│  (Warehouse DB)       │   dw.fact_achievement_unlock, dw.fact_library,
└───────────────────────┘   dw.fact_review, dw.fact_achievement
```

---

## 2. Phase 00 — Landing Validation

**Job:** `00_validate_landing.kjb`
**Transforms:** `00_find_unprocessed_partitions.ktr`, `00_validate_required_files.ktr`

### What it does
1. Scans `Datasets/landing/` for subdirectories named `extract_dt=YYYYMMDD`
2. Cross-references against `dbo.stg_load_audit` (where `status = 'success'`) to find partitions not yet loaded
3. Picks the **oldest unprocessed partition** and stores its path in a Pentaho variable for downstream transforms
4. Optionally validates that the partition directory contains all 5 required CSVs

### Data cleaning at this stage
- **Idempotency guard:** Already-processed partitions are skipped → prevents duplicate loads
- No data-level cleaning occurs here — this is purely file-system validation

---

## 3. Phase 05 — Raw File Read (Optional Preview)

**Transforms:** `05_load_raw_*.ktr` (9 files)

These are **optional read-only** transforms that preview the raw CSV contents. They exist to:
- Validate CSV structure (headers, column count)
- Log sample rows for debugging

**No data is written** at this stage — these are diagnostic tools.

---

## 4. Phase 10 — CSV → MSSQL Staging

**Transforms:** `10_load_mssql_staging_*.ktr` (5 transforms, run in **parallel**)

This phase loads raw CSVs into MSSQL `DW_Staging` staging tables. All staging columns are `NVARCHAR(MAX)` — no type enforcement at this stage.

### 4.1 `10_load_mssql_staging_players.ktr`
- **Source:** `players.csv` (columns: `playerid`, `country`, `created`)
- **Target:** `dbo.stg_players`
- **Cleaning:**
  - Pentaho CSV file input reads all fields as strings
  - `loaded_at` column auto-populated with `SYSUTCDATETIME()` for temporal tracking
  - No dedup, no validation, no type casting — raw ingestion only

### 4.2 `10_load_mssql_staging_history.ktr`
- **Source:** `history.csv` (columns: `playerid`, `achievementid`, `date_acquired`)
- **Target:** `dbo.stg_history`
- **Cleaning:**
  - Same raw ingestion approach — all `NVARCHAR(MAX)`
  - `loaded_at` timestamp added
  - The `date_accquired` typo column (if present in CSV) is handled by the CSV reader reading only the configured columns

### 4.3 `10_load_mssql_staging_reviews.ktr`
- **Source:** `reviews.csv` (columns: `reviewid`, `playerid`, `gameid`, `review`, `helpful`, `funny`, `awards`, `posted`)
- **Target:** `dbo.stg_reviews`
- **Cleaning:**
  - All fields stored as `NVARCHAR(MAX)`, including `review` text (preserves full UTF-8 content)
  - `loaded_at` timestamp added
  - No text normalization or encoding conversion at this stage

### 4.4 `10_load_mssql_staging_library.ktr`
- **Source:** `purchased_games.csv` (columns: `playerid`, `library`)
- **Target:** `dbo.stg_purchased_games`
- **Cleaning:**
  - The `library` field is stored as-is — it contains a JSON array string: `[{"appid": 10, "playtime_mins": 0}, ...]`
  - No JSON parsing occurs at this stage

### 4.5 `10_load_mssql_staging_private.ktr`
- **Source:** `private_steamids.csv` (column: `playerid`)
- **Target:** `dbo.stg_private_steamids`
- **Cleaning:**
  - Simple single-column load

### Additional staging loads (not in the 5 core)
- `stg_achievements` — from `achievements.csv` (`achievementid`, `gameid`)
- `stg_games` — from `games.csv` (game metadata)
- These feed the dimension tables in Phase 20

---

## 5. Phase 20 — MSSQL Staging → Postgres DW (Data Cleaning Focus)

**Transforms:** `20_build_postgres_dw_*.ktr` (run **sequentially** — dimensions before facts)

This is where **all major data cleaning, deduplication, type casting, and integrity enforcement** happens.

### Execution Order

```
1. 20_build_postgres_dw_dim_game.ktr         → dw.dim_game
2. 20_build_postgres_dw_dim_player.ktr       → dw.dim_player
3. 20_build_postgres_dw_dim_private_steamid.ktr → marks dim_player.is_private = TRUE
4. 20_build_postgres_dw_fact_achievement.ktr → dw.fact_achievement
5. 20_build_postgres_dw_fact_history.ktr     → dw.fact_achievement_unlock
6. 20_build_postgres_dw_fact_library.ktr     → dw.fact_library (via dw.stg_library_temp)
7. 20_build_postgres_dw_fact_review.ktr      → dw.fact_review
```

> **Critical:** Dimensions MUST load before facts, because the fact triggers reference dimension tables.

---

### 5.1 `20_build_postgres_dw_dim_game.ktr` — Game Dimension

**SQL Query (from MSSQL staging):**
```sql
SELECT gameid, title, release_date
FROM (
    SELECT gameid, title, release_date,
           ROW_NUMBER() OVER(PARTITION BY gameid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_games
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `ROW_NUMBER() PARTITION BY gameid` — keeps only the latest version of each game |
| Pentaho Select Values | Type casting | `release_date`: String → Date (`yy-MM-dd` format) |
| Pentaho Insert/Update | Upsert | Matched on `gameid` → updates `title` and `release_date` if the game already exists |

### 5.2 `20_build_postgres_dw_dim_player.ktr` — Player Dimension

**SQL Query:**
```sql
SELECT playerid, country, created
FROM (
    SELECT playerid, country, created,
           ROW_NUMBER() OVER(PARTITION BY playerid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_players
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `ROW_NUMBER() PARTITION BY playerid` — keeps latest player record |
| Pentaho Select Values | Type casting | `created`: String → Timestamp (`%Y-%m-%d %H:%M:%S` format) |
| Pentaho Insert/Update | Upsert | Matched on `playerid` → updates country and created date |
| Parallelism | Performance | Insert/Update step runs with **2 copies** for throughput |

### 5.3 `20_build_postgres_dw_dim_private_steamid.ktr` — Privacy Flagging

**SQL Query:**
```sql
SELECT playerid
FROM dbo.stg_private_steamids
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL UPDATE on Postgres | State mutation | Sets `dw.dim_player.is_private = TRUE` for all matching player IDs |

> **Note:** This does NOT delete players from the dimension — it flags them. The ML pipeline then filters with `WHERE is_private = FALSE`.

### 5.4 `20_build_postgres_dw_fact_achievement.ktr` — Achievement Dimension

**SQL Query:**
```sql
SELECT achievementid, gameid
FROM (
    SELECT achievementid, gameid,
           ROW_NUMBER() OVER(PARTITION BY achievementid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_achievements
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `ROW_NUMBER() PARTITION BY achievementid` |
| Postgres trigger (`trg_achieve_dim_fk`) | FK enforcement | If `gameid NOT IN dw.dim_game` → auto-creates stub game |
| Postgres trigger | Null rejection | If `achievementid IS NULL` → row dropped |
| Postgres trigger | De-duplication | Prevents duplicate inserts on PK `achievementid` |

### 5.5 `20_build_postgres_dw_fact_history.ktr` — Achievement Unlock Facts

**SQL Query:**
```sql
SELECT playerid, achievementid, date_acquired
FROM (
    SELECT playerid, achievementid, date_acquired,
           ROW_NUMBER() OVER(PARTITION BY playerid, achievementid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_history
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `PARTITION BY playerid, achievementid` — **keeps only one row per player+achievement** (this is where a data diff can occur — see note below) |
| Pentaho Select Values | Type casting | `date_acquired`: String → Timestamp (`DD/MM/YYYY HH:mm` format, timezone: UTC) |
| Pentaho Insert/Update | Upsert | Matched on `(playerid, achievementid)` → Postgres PK |
| Postgres trigger (`trg_achieve_fk`) | FK enforcement | If `playerid NOT IN dim_player` → row dropped. If `achievementid NOT IN fact_achievement` → auto-creates stub (after recent fix) |
| Error handling | Logging | Failed rows routed to `err_log.csv` (step error handling enabled) |
| Parallelism | Performance | Insert/Update runs with **4 copies** |

> **⚠️ Important dedup difference:** The DW deduplicates on `(playerid, achievementid)` ignoring `date_acquired`. The original Python pipeline deduplicates on `(playerid, achievementid, date_acquired)`. This means if a player has the same achievement recorded at two different times, the DW keeps one, the original keeps both.

### 5.6 `20_build_postgres_dw_fact_library.ktr` — Library Facts (Game Ownership)

This is the **most complex transform** in the pipeline.

**SQL Query:**
```sql
SELECT playerid, library
FROM (
    SELECT playerid, library,
           ROW_NUMBER() OVER(PARTITION BY playerid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_purchased_games
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `PARTITION BY playerid` — keeps latest library snapshot per player |
| Pentaho Table Output | Staging | Writes `(playerid, library_json_string)` to `dw.stg_library_temp` (truncate-and-reload strategy) |
| Postgres SQL (post-load) | JSON explosion | A separate SQL step parses the JSON library string and inserts individual `(playerid, appid, playtime_mins)` rows into `dw.fact_library` |
| Postgres trigger (`trg_library_fk`) | FK enforcement | If `playerid NOT IN dim_player` → row dropped. If `appid NOT IN dim_game` → auto-creates stub game record (after recent fix) |
| Postgres trigger | Null handling | `playtime_mins` → `COALESCE(playtime_mins, 0)` (defaults NULL to 0) |
| Postgres trigger | De-duplication | Prevents duplicate inserts on PK `(playerid, appid)` |

**Library JSON explosion process:**
```
Input:  playerid=12345, library='[{"appid":730,"playtime_mins":500},{"appid":570,"playtime_mins":0}]'
                    ↓ (JSON parse + unnest)
Output: (12345, 730, 500)
        (12345, 570, 0)
```

### 5.7 `20_build_postgres_dw_fact_review.ktr` — Review Facts

**SQL Query:**
```sql
SELECT reviewid, playerid, gameid, review, helpful, funny, awards, posted
FROM (
    SELECT reviewid, playerid, gameid, review, helpful, funny, awards, posted,
           ROW_NUMBER() OVER(PARTITION BY reviewid ORDER BY loaded_at DESC) as rn
    FROM dbo.stg_reviews
) sub
WHERE rn = 1
```

**Data cleaning:**
| Step | Type | Description |
|------|------|-------------|
| SQL-level dedup | Deduplication | `PARTITION BY reviewid` — keeps latest version of each review |
| Pentaho Select Values | Type casting | `helpful`, `funny`, `awards`: String → Integer |
| Pentaho Select Values | Type casting | `posted`: String → Date (`yy-MM-dd` format) |
| Pentaho Select Values | Type casting | `review`: explicitly set to String type with length `1073741823` (preserves full text) |
| Pentaho Insert/Update | Upsert | Matched on `reviewid` |
| Postgres trigger (`trg_review_fk`) | FK enforcement | If `playerid NOT IN dim_player` → row dropped. If `gameid NOT IN dim_game` → falls back to `'-1'` placeholder |
| Error handling | Logging | Failed rows routed to `err_log.csv` |

---

## 6. Postgres DW — Trigger-Based Integrity (Data Cleaning at DB Level)

The DW has **4 `BEFORE INSERT OR UPDATE` triggers** that act as a final data quality gate. These fire on every row inserted by the Phase 20 Pentaho transforms.

### Summary of trigger behavior

| Trigger | Table | NULL PK | Missing Player | Missing FK | Duplicate PK |
|---------|-------|---------|----------------|------------|-------------|
| `trg_review_fk` | `fact_review` | Drop row | Drop row | `gameid → '-1'` | Drop row |
| `trg_achieve_dim_fk` | `fact_achievement` | Drop row | N/A | Auto-create stub game | Drop row |
| `trg_achieve_fk` | `fact_achievement_unlock` | Drop row | Drop row | Auto-create stub | Drop row |
| `trg_library_fk` | `fact_library` | Drop row | Drop row | Auto-create stub game | Drop row |

### Default sentinel values
- `dim_player` has a default `-1` row (`playerid='-1'`, `country='Unknown'`)
- `dim_game` has a default `-1` row (`gameid='-1'`, `title='Unknown'`)
- `fact_achievement` has a default `-1` row
- Non-PK FK columns can fall back to these sentinels
- PK columns are never rewritten — the row is dropped instead

---

## 7. Complete Data Cleaning Inventory

### Per-table summary of all cleaning operations

| Data Entity | Cleaning Step | Where | Mechanism |
|------------|---------------|-------|-----------|
| **All tables** | Temporal tracking | MSSQL staging | `loaded_at DEFAULT SYSUTCDATETIME()` on every staging row |
| **All tables** | Deduplication (SQL) | Phase 20 KTR | `ROW_NUMBER() OVER(PARTITION BY <pk> ORDER BY loaded_at DESC) WHERE rn=1` |
| **All tables** | Deduplication (trigger) | Postgres DW | `BEFORE INSERT` triggers check for existing PK |
| **Players** | Type casting | Pentaho Select Values | `created`: NVARCHAR → Timestamp |
| **Players** | Privacy flagging | Postgres DW | `is_private = TRUE` via private steamids update |
| **History** | Type casting | Pentaho Select Values | `date_acquired`: NVARCHAR → Timestamp (UTC) |
| **History** | FK stub creation | Postgres trigger | Missing achievements auto-stubbed in `fact_achievement` and `dim_game` |
| **History** | Null rejection | Postgres trigger | Rows with NULL `playerid` or `achievementid` are dropped |
| **Reviews** | Type casting | Pentaho Select Values | `helpful/funny/awards`: NVARCHAR → Integer; `posted`: NVARCHAR → Date |
| **Reviews** | FK fallback | Postgres trigger | Missing `gameid` → replaced with sentinel `'-1'` |
| **Reviews** | Player validation | Postgres trigger | Missing `playerid` → row dropped |
| **Library** | JSON explosion | Postgres SQL | Single row with JSON array → multiple `(playerid, appid, playtime)` rows |
| **Library** | Null handling | Postgres trigger | `playtime_mins` NULL → 0 |
| **Library** | FK stub creation | Postgres trigger | Missing games auto-stubbed in `dim_game` |
| **Games** | Type casting | Pentaho Select Values | `release_date`: NVARCHAR → Date |
| **Achievements** | FK stub creation | Postgres trigger | Missing `gameid` → auto-stubbed in `dim_game` |

---

## 8. Error Handling

| Mechanism | Where | What happens |
|-----------|-------|-------------|
| **Step error routing** | Pentaho transforms (history, review) | Rows that fail type conversion or insert are routed to `err_log.csv` |
| **Trigger RETURN NULL** | Postgres triggers | Invalid rows silently dropped (NULL PK, missing required FK) |
| **Audit log** | `dbo.stg_load_audit` | Each completed load writes a row with row counts and status |
| **Pentaho logging** | `dbo.pentaho_logging` | Job-level logging (start/end times, error counts) |

---

## 9. Idempotency Design

The pipeline is designed to be **safe to re-run**:

1. **Partition-based processing:** `00_validate_landing.kjb` only processes partitions not yet recorded in `stg_load_audit`
2. **Staging dedup:** `ROW_NUMBER() PARTITION BY ... ORDER BY loaded_at DESC` ensures only the latest version of each entity is forwarded to the DW
3. **Upsert semantics:** Phase 20 transforms use Pentaho's "Insert/Update" step — existing DW rows are updated, new rows are inserted
4. **Trigger-level dedup:** All triggers have `IF EXISTS (SELECT 1 FROM ... WHERE <pk> = NEW.<pk>) THEN RETURN NULL` to silently skip duplicates
5. **Library truncate-and-reload:** `stg_library_temp` uses `<truncate>Y</truncate>` — always starts fresh

---

## 10. Known Limitations & Notes

1. **All staging columns are `NVARCHAR(MAX)`:** No type validation occurs at the MSSQL level. Invalid values (e.g., non-date strings in `created`) only fail at the Pentaho Select Values step during Phase 20.

2. **Review text encoding path:** Review text passes through: UTF-8 CSV → Pentaho CSV reader → MSSQL `NVARCHAR(MAX)` → Pentaho reads back → Postgres `TEXT`. Each hop is a potential encoding conversion point.

3. **History dedup scope is narrower than original:** The DW deduplicates on `(playerid, achievementid)`, ignoring `date_acquired`. The original Python pipeline deduplicates on all three columns. This means re-unlocks of the same achievement are collapsed in the DW.

4. **Library explosion depends on dim_game coverage:** The `fact_library` trigger auto-creates stub `dim_game` records for unknown game IDs. This was recently added to prevent silent data loss — previously, games not in `dim_game` were dropped.

5. **Date format `DD/MM/YYYY HH:mm`:** The history transform parses `date_acquired` in this format — ensure the raw CSV uses this exact format, not `YYYY-MM-DD`.

6. **Commit sizes vary:** `dim_player` uses 20,000-row commits, `fact_achievement_unlock` uses 100-row commits (smaller for large-volume inserts with triggers), `fact_library` uses 20,000-row commits to `stg_library_temp`.
