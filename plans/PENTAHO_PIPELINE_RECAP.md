# Pentaho Data Integration (PDI) Pipeline Recap

This document provides a high-level overview of the data engineering pipeline built using Pentaho Data Integration (Spoon). Based on the project structure and file naming conventions, the pipeline follows a classic multi-tier Data Warehouse architecture, moving data from raw files through staging into a structured Data Warehouse, and finally building Data Marts for analytics.

## Architecture Overview

The pipeline is orchestrated across several distinct phases, moving data across different storage technologies:
1. **Landing/Raw:** CSV/JSON files.
2. **Staging:** Microsoft SQL Server (MSSQL).
3. **Data Warehouse (DW):** PostgreSQL.
4. **Data Mart (DM):** Likely PostgreSQL or specialized flattened tables for ML/Analytics.

---

## Phase Breakdown

### Phase 0: Validation & Preparation
**Files:** `00_validate_landing.kjb`, `00_find_unprocessed_partitions.ktr`, `00_validate_required_files.ktr`
* **Purpose:** Checks the `/landing/` directory for new, unprocessed data partitions (e.g., partitioned by extraction date).
* **Action:** Validates that all required files (history, players, reviews, etc.) are present before starting a run, preventing partial data loads and pipeline failures.

### Phase 05: Load Raw Data
**Files:** `05_master_load_raw.kjb`, `05_load_raw_*.ktr`
* **Purpose:** Moves data from the partitioned `/landing/` area into the consolidated `/raw/` area.
* **Action:** Reads CSVs like `achievements.csv`, `friends.csv`, `games.csv`, `history.csv`, `players.csv`, `prices.csv`, `private_steamids.csv`, `purchased_games.csv`, and `reviews.csv` and standardizes their format or merges them into a primary raw storage location.

### Phase 10: Staging (MSSQL)
**Files:** `10_load_mssql_staging_*.ktr`
* **Purpose:** Loads raw file data into an operational Staging Database hosted on MS SQL Server.
* **Action:** Data mappings and initial type casting are performed here. The tables likely correspond directly to the raw files (e.g., `staging_history`, `staging_library`, `staging_players`, `staging_private`, `staging_reviews`).

### Phase 20: Data Warehouse Modeling (PostgreSQL)
**Orchestrators:** `build_dw.kjb` (Main), `build_dw_dim_phase.kjb`, `build_dw_bridge_fact_phase.kjb`, `build_dw_extra.kjb`
**Transforms:** `20_build_postgres_dw_*.ktr`
* **Purpose:** Transforms the staged data into a dimensional Star or Snowflake schema inside a PostgreSQL Data Warehouse.
* **Action:** 
  * **Dimension Phase (`dim_*`):** Loads dimensional tables containing descriptive attributes (Achievements, Games, Players, Prices, Private SteamIDs). These likely generate Surrogate Keys (SKs).
  * **Fact & Bridge Phase (`fact_*`, `bridge_*`):** Loads transactional and associative data using the SKs generated in the dimension phase. Handles bridging for many-to-many relationships (e.g., `bridge_friend`) and vast quantitative records (`fact_history`, `fact_library`, `fact_review`).
  * **Extra Phase:** Calculates extra metrics or aggregates related to games (`game_extra`).

### Phase 30: Data Mart & Features
**Files:** `build_dm.kjb`, `30_build_datamart_features.ktr`
* **Purpose:** Prepares flattened datasets (Data Marts) specialized for downstream consumers, like the Machine Learning anomaly detection models.
* **Action:** Extracts and aggregates features from the normalized Data Warehouse facts and dimensions to serve directly into the `ML_analytics` pipeline.

### Orchestration
**Files:** `master.kjb`, `pre_master.kjb`, `full_run.kjb`, `run_dss_refresh.kjb`
* **Purpose:** Acts as the entry points and controllers for the complete execution of the pipeline.
* **Action:** `full_run.kjb` or `master.kjb` sequentially triggers Phase 0 -> Phase 05 -> Phase 10 -> Phase 20 -> Phase 30. They handle error catching, logging, and state management (like marking a landing partition as "processed").
