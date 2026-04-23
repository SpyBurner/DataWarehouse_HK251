# Migration guide: split at Postgres Datamart (Pentaho upstream, ML downstream)

This document is a **step-by-step playbook** for migrating this repo into a Decision Support System (DSS) architecture where:

**Raw CSV drops → Pentaho → MSSQL Staging → Pentaho → Postgres DW → Pentaho → Postgres Datamart → (new ML/analytics repo)**

Key rule: **the separation boundary is the Postgres datamart**. Everything upstream is Pentaho-owned. The ML repo consumes datamart outputs and optionally writes scores back.

---

## 0) End state (what “done” looks like)

1. A Python crawler produces **only CSV result drops** into a landing folder.
2. Pentaho ingests those CSV drops into MSSQL staging, transforms into Postgres DW, then builds a Postgres datamart.
3. The datamart exposes a stable, versioned feature dataset (recommended: one row per `playerid`).
4. A separate “ML & analytics” repo reads datamart features, trains/scores models, and writes anomaly scores back to the datamart.
5. Streamlit (or any BI tool) reads scores from the datamart.

---

## 0.1 Migration sequence (do this in order)

1. Choose the datamart contract (Contract A recommended).
2. Define crawler CSV schemas + landing convention (folders, `_SUCCESS`, `manifest.json`).
3. Provision databases + tables (MSSQL staging, Postgres DW, Postgres datamart).
3. Build Pentaho validation + MSSQL staging loads.
4. Build Pentaho DW upserts in Postgres.
5. Build Pentaho datamart (feature table/view + refresh log).
6. Create the new ML repo and point it to datamart as the production source.
7. Add ML score write-back table and populate it from the ML repo.
8. Cut over dashboards/UI to read from datamart score table.

---

## 1) Decide the data contract at the datamart boundary

To maximize Pentaho and make the separation clean, pick **one** primary contract:

### Contract A (recommended): datamart publishes player-level features

Datamart provides a table/view like `dm_steam_player_features_v1`:
- one row per `playerid`
- columns = the feature names the model consumes (stable names)

The ML repo never needs raw events. It just consumes features.

### Contract B (fallback): datamart publishes conformed facts

Datamart provides facts (achievement events, reviews, library rows) and Python computes features. This is workable, but it weakens the “Pentaho owns upstream” separation.

If your goal is a hard boundary at the datamart, prefer **Contract A**.

---

## 2) Split the codebase into two deliverables

You said you will copy only required files into another repo. The clean split is:

### 2.1 New repo A: “ML & analytics” (what you copy)

Copy the minimum that is needed for modelling, scoring, evaluation, and UI. A reasonable starting set from this workspace:

- `main.py` (pipeline orchestration)
- `streamlit_app.py` (DSS UI)
- `run_testcase_evaluation.py` (offline evaluation)
- `requirements.txt`
- `src/` (core ML code):
  - `src/models.py`
  - `src/evaluate.py`
  - `src/active_learning.py` (optional, if you want HITL)
  - `src/features.py` (optional if Contract A; required if Contract B)

What you do **not** copy into the ML repo (because Pentaho owns upstream):
- `src/data_prep.py` (Phase 1 CSV→parquet ETL becomes Pentaho)
- `data/` folders (`data/raw`, `data/crawled`, `data/processed`, archives)
- merge scripts for local raw files (`merge_crawled_purchased_games.py`, etc.)

#### Mapping: current Python “data processing” → Pentaho

Use this as a checklist to ensure upstream logic is re-homed cleanly:

- Local file landing + merging (`data/raw/`, `data/crawled/`, `merge_crawled_purchased_games.py`) → replaced by the **crawler landing drops** + Pentaho staging loads.
- CSV cleaning/dedup/private filtering (`src/data_prep.py`) → replaced by:
  - Pentaho landing validation (`00_validate_landing.kjb`)
  - Pentaho MSSQL staging transforms (`10_load_mssql_staging_*.ktr`)
  - DW upsert rules (`20_build_postgres_dw_*.ktr`)
- Feature engineering (`src/features.py`) → ideally moved into the **datamart build** (`30_build_datamart_*.ktr`) under Contract A.

Net effect: the ML repo should not own any “raw data preparation” concerns.

### 2.2 External deliverable B: “Upstream data pipeline” (Pentaho + DB)

This includes:
- Pentaho jobs/transforms (`*.kjb`, `*.ktr`)
- DDL for MSSQL staging, Postgres DW, Postgres datamart
- the file landing convention for crawler CSV drops

---

## 3) Crawling strategy (Python crawler → CSV drops only)

Requirement: crawling can be Python, but **Pentaho input is strictly the crawler’s CSV outputs**.

### 3.1 Crawler output: landing folder contract

Use a deterministic landing convention so Pentaho can pick up drops safely:

Example layout (recommended):

```
landing/
  steam/
    extract_dt=2026-04-23T120000Z/
      players.csv
      history.csv
      reviews.csv
      library.csv
      private_steamids.csv
      manifest.json
      _SUCCESS
```

Notes:
- `extract_dt=...` is the partition key. Pentaho uses it to load incrementally.
- `_SUCCESS` exists only when the crawler finished writing all files.
- `manifest.json` contains row counts, schema version, and (optional) checksums.

Recommended `manifest.json` fields (example):
- `schema_version`: e.g. `steam_extract_v1`
- `extract_dt`: must match the folder
- `files`: map of filename → `{rows, columns, sha256(optional)}`
- `crawler_version`: git SHA / tag
- `generated_at_utc`

### 3.2 Prefer relational crawler outputs (avoid JSON-in-CSV)

To maximize Pentaho and simplify staging/DW loads:
- If you can: output one-row-per-item `library_items.csv`.

However, per your constraint, the crawler will output **`library.csv` as-is**.

Your stated format is a list-like string such as `[a,b,c]` (no exploding in crawler). That is fine.

Pentaho is strongest when ingesting clean tabular CSV.

Alternative (strictest “staging is closest to source”):
- Have the crawler write the **raw API payload** as a text column in CSV (one row per API call / player / extract).
- Keep staging as raw-as-possible, and let Pentaho do the array “explode to rows” later when building the DW.

Both approaches are valid. Choose based on what you want to optimize:
- maximize simplicity/performance → crawler outputs already-normalized `library_items.csv`
- maximize “closest to source” + auditability → crawler outputs `library.csv` with a list-string column, Pentaho explodes during staging→DW

### 3.3 Incremental crawling and late-arriving data

Define an incremental policy that matches DSS refresh:
- **Daily batch** is simplest: crawl a target set of players daily, output one partition.
- Keep `extract_dt` in every output table.
- Allow late arrivals by allowing Pentaho to re-load / upsert for the last N partitions (e.g., last 7 days).

### 3.4 Crawler scope (what to crawl)

At minimum (matching the current ML logic), crawl/export:
- player profile: `players.csv` (playerid, country, created)
- achievement history: `history.csv` (playerid, achievementid, date_acquired, derived gameid if available)
- reviews: `reviews.csv` (reviewid, playerid, gameid, review text, posted)
- library: `library.csv` (playerid, library_list_string)
- private IDs: `private_steamids.csv` (playerid)

If you later expand features, add new CSVs but do not break existing columns.

### 3.5 Operations: how crawling and Pentaho fit together

Keep responsibilities explicit:

- The crawler is responsible for:
  - writing complete partitions
  - writing `_SUCCESS` last
  - never modifying previously “published” partitions in place

- Pentaho is responsible for:
  - only ingesting partitions that contain `_SUCCESS`
  - recording ingestion status (success/failure) per partition
  - archiving or marking partitions as “processed”

Scheduling options (pick one):
- Run crawler via OS scheduler (Windows Task Scheduler / cron) → writes drops → Pentaho runs on a schedule and picks the latest complete drop.
- Run crawler manually for ad-hoc batches → Pentaho run is triggered after drop is published.

This keeps the rule intact: Pentaho inputs are strictly CSV results.

---

## 3.6 Special note: `library.csv` list-string format

You said `library.csv` contains a list string like `[a,b,c]`.

Guidance:
- Stage it as text (do not “fix” it in staging).
- In the staging→DW transform, parse it into one row per `(playerid, appid)`.

Practical parsing rules to standardize:
- Decide whether the list contains numeric appids (recommended) or strings.
- Strip brackets `[` `]`, split on commas, trim whitespace.
- Treat empty list (`[]`) as zero items.
- Log/route malformed rows to an error table with the raw string.

---

## 4) Pentaho upstream implementation (step-by-step)

Pentaho can fully handle everything before the datamart. The simplest pattern is: **one top-level Job that orchestrates multiple Transforms**.

Suggested top-level orchestration job (one “run”):
- `run_dss_refresh.kjb`:
  1) call `00_validate_landing.kjb`
  2) run all `10_load_mssql_staging_*.ktr`
  3) run all `20_build_postgres_dw_*.ktr`
  4) run all `30_build_datamart_*.ktr`
  5) call `40_publish.kjb`
  6) notify (email/Slack/log table)

### 4.1 Step 1 — Validate landing drops

Pentaho Job: `00_validate_landing.kjb`

Checks:
- locate newest `extract_dt=...` folder
- ensure `_SUCCESS` exists
- validate required files exist
- validate row counts and schema version from `manifest.json`
- move “bad drops” to a quarantine folder and alert

### 4.2 Step 2 — Load MSSQL staging (raw-ish)

Pentaho Transform(s): `10_load_mssql_staging_*.ktr`

Principles:
- staging is close to source; minimal business logic
- always include `extract_dt` and `source_file` (lineage)

Recommended staging tables (examples):
- `stg_players`
- `stg_history`
- `stg_reviews`
- `stg_library_raw` (recommended: store `library.csv` list-string payload as text)
- `stg_library_items` (optional: only if you decide to explode earlier than DW)
- `stg_private_steamids`

Array endpoints note (library, friends, etc.):
- Pentaho can explode arrays/nested JSON into one-row-per-item (similar to PowerBI “expand to new rows”).
- To keep staging closest to source, store the raw payload in `stg_library_raw` and explode it in Step 3 (DW build).

Loading tips:
- enforce UTF-8 and strict quoting
- reject rows that break parsing into an error table
- add dedup keys where possible (e.g. `reviewid`, `(playerid, achievementid, date_acquired)`)

### 4.3 Step 3 — Build/Upsert Postgres DW (conformed)

Pentaho Transform(s): `20_build_postgres_dw_*.ktr`

DW goal: conformed dims and facts that are stable and reusable.

Typical objects:
- `dim_player` (playerid, country, created, …)
- `dim_game` (if you have it)
- `fact_achievement_unlock` (playerid, gameid, unlocked_at)
- `fact_review` (reviewid, playerid, gameid, posted_at, review_text, …)
- `fact_library` (playerid, appid, playtime_mins)

If you staged raw array payloads:
- explode `stg_library_raw` into `fact_library` here (staging→DW transform)
- keep a lineage link: `extract_dt`, `source_endpoint`, and optionally a `payload_hash` so you can trace DW rows back to the staged raw payload

For your `library.csv` list-string:
- `stg_library_raw.library_list_string` is the staged text column
- DW step parses/explodes to `fact_library(playerid, appid, extract_dt, ...)`

Upsert strategy:
- insert new records by primary key
- update mutable attributes (e.g., country) using a last-seen rule
- keep `extract_dt` for audit

### 4.4 Step 4 — Build Postgres datamart (the boundary)

Pentaho Transform(s): `30_build_datamart_*.ktr`

If using Contract A (recommended), this step produces:

**A) Feature dataset** `dm_steam_player_features_v1`
- one row per `playerid`
- stable feature columns

**B) Optional queue dataset** `dm_steam_review_queue`
- candidates for human labeling (HITL)

### 4.5 Step 5 — Publish & refresh

Pentaho Job: `40_publish.kjb`

Examples:
- refresh materialized views
- analyze/vacuum tables (Postgres)
- write a “datamart_refresh_log” row (refresh status + row counts)

---

## 5) Datamart schema: what the ML repo expects

### 5.1 Required: feature view/table (Contract A)

Create `dm_steam_player_features_v1` with feature columns named exactly as the ML code expects.

Baseline feature groups used by this repo (25 total):
- Speed: `median_unlock_interval_sec`, `std_unlock_interval_sec`, `cv_unlock_interval`, `max_achievements_per_minute`, `max_achievements_per_day`
- Temporal: `night_activity_ratio`, `hour_entropy`, `activity_density`
- Diversity: `total_achievements`, `library_size`, `achievement_game_ratio`, `top1_game_concentration`, `top3_game_concentration`, `game_hhi`, `avg_achievements_per_game`
- Reviews: `total_reviews`, `review_unplayed_ratio`, `review_duplication_rate`, `avg_review_length`, `min_review_length`
- Account age: `days_before_first_achievement`, `account_age_days`
- Playtime: `zero_playtime_achievements_ratio`, `total_playtime_mins`, `playtime_per_achievement`

Versioning:
- introduce `*_v2` as a new object when you add/remove/rename columns
- keep `v1` stable so models don’t silently break

### 5.2 Recommended: score table (write-back from ML)

Create `dm_steam_player_anomaly_scores` (name flexible) with:
- `playerid`
- `scored_at`
- `model_version` (string you control)
- `composite_score`, `is_anomaly`, component fields (`xgb_pct`, `if_pct`, `xgb_proba` if you keep it)

This is the DSS-facing table BI dashboards should use.

---

## 5.3 Provisioning databases and tables (MSSQL + Postgres)

You asked whether this can be automated and whether you should create schemas first.

### Recommendation (most robust)

1) **Create databases and tables first** (DDL as code, version controlled).
2) Use Pentaho primarily for:
- file ingestion
- data validation
- upserts/transforms

Pentaho *can* execute DDL, but treating schema as a separate, versioned “infrastructure” concern avoids accidental drift and makes deployments repeatable.

### What to create on MSSQL (staging)

Create:
- a database, e.g. `steam_staging`
- a schema, e.g. `stg`
- tables that mirror the CSVs closely

Minimum staging tables:
- `stg.stg_players`
- `stg.stg_history`
- `stg.stg_reviews`
- `stg.stg_library_raw` (contains the list-string)
- `stg.stg_private_steamids`

Also recommended:
- `stg.stg_load_audit` (partition ingested, row counts, status)
- `stg.stg_reject_rows` (bad CSV rows / malformed list-strings)

### What to create on Postgres (DW + datamart)

Create:
- a DW database or schema (e.g. `dw`) containing dims/facts
- a datamart schema (e.g. `dm`) containing feature view/table and score table

Minimum DW tables (examples):
- `dw.dim_player`
- `dw.fact_achievement_unlock`
- `dw.fact_review`
- `dw.fact_library` (exploded items)

Minimum datamart objects:
- `dm.dm_steam_player_features_v1`
- `dm.dm_steam_player_anomaly_scores`
- optional `dm.dm_datamart_refresh_log`

### Automation options (choose one)

**Option A — DB migration tool (recommended):**
- Use Flyway or Liquibase (or similar) to apply SQL migrations in order.
- Run it in CI/CD or a scheduled deployment step.

**Option B — Pentaho runs DDL at startup:**
- Add a first step in `run_dss_refresh.kjb` that runs “create schema if not exists / create table if not exists”.
- Works, but be careful with schema drift and permissions.

**Option C — Simple scripted provisioning:**
- Keep `sql/` scripts in version control.
- Run them with `sqlcmd` (MSSQL) and `psql` (Postgres) during environment setup.

If you want strict separation of concerns, use Option A or C, and keep Pentaho focused on data movement + transformations.

---

## 6) ML repo changes (downstream, after the split)

In the new ML repo, your production data source becomes **Postgres datamart**.

### 6.1 Step 1 — Add a datamart datasource

Implement a loader that reads `dm_steam_player_features_v1` into a DataFrame. Keep the interface narrow:
- input: connection string + view name
- output: DataFrame indexed by `playerid`

### 6.2 Step 2 — Run training/scoring against datamart

Update `main.py` (or a new entrypoint) to:
- read features from datamart
- train models and generate scores
- write scores back to `dm_steam_player_anomaly_scores`

### 6.3 Step 3 — Streamlit reads from datamart

Update Streamlit to:
- query `dm_steam_player_anomaly_scores` for the selected player
- optionally join back to `dm_steam_player_features_v1` for explanation visuals

---

## 7) Cutover plan (safe migration)

1. Run the current repo (file/parquet mode) on a frozen snapshot and keep outputs.
2. Stand up Pentaho staging→DW→datamart on the same snapshot partition.
3. Validate the datamart feature table matches the Python-produced feature table (column names and value distributions).
4. Run ML scoring from datamart and compare top-N suspicious accounts vs baseline.
5. Enable write-back of scores; build the DSS dashboard against `dm_steam_player_anomaly_scores`.
6. Switch production to: crawler → Pentaho → datamart → ML scoring → datamart scores.

---

## 8) Checklist (quick)

- Crawler produces partitioned CSV drops with `_SUCCESS` + `manifest.json`.
- Pentaho validates drops, loads MSSQL staging, builds Postgres DW, builds Postgres datamart.
- Datamart exposes `dm_steam_player_features_v1` with stable column names.
- ML repo reads datamart features and writes `dm_steam_player_anomaly_scores`.
- Streamlit/BI reads from datamart score table.
