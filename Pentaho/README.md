# Pentaho Pipeline — Steam Crawler ETL

This folder contains all Pentaho Data Integration (PDI/Spoon) files for the
**Steam Crawler → MSSQL Staging → Postgres DW → Datamart** pipeline.

For the full guide, see: [`../pentaho_pipeline_guide.md`](../pentaho_pipeline_guide.md)

---

## Folder structure

```
Pentaho/
├── jobs/
│   ├── run_dss_refresh.kjb              # Master orchestration job (entry point)
│   └── 00_validate_landing.kjb          # Landing validation + partition selection
│
└── transforms/
    ├── 00_find_unprocessed_partitions.ktr  # Diff landing/ vs stg_load_audit
    ├── 00_validate_required_files.ktr      # Assert all 5 CSVs exist (optional)
    │
    ├── 10_load_mssql_staging_players.ktr   # players.csv        → dbo.stg_players
    ├── 10_load_mssql_staging_history.ktr   # history.csv        → dbo.stg_history
    ├── 10_load_mssql_staging_reviews.ktr   # reviews.csv        → dbo.stg_reviews
    ├── 10_load_mssql_staging_library.ktr   # purchased_games.csv → dbo.stg_library_raw
    ├── 10_load_mssql_staging_private.ktr   # private_steamids.csv → dbo.stg_private_steamids
    │
    ├── 20_build_postgres_dw_dim_player.ktr      # stg_players    → dw.dim_player
    ├── 20_build_postgres_dw_fact_achievement.ktr # stg_history    → dw.fact_achievement_unlock
    ├── 20_build_postgres_dw_fact_review.ktr     # stg_reviews    → dw.fact_review
    ├── 20_build_postgres_dw_fact_library.ktr    # stg_library_raw → dw.fact_library (explode)
    │
    └── 30_build_datamart_features.ktr           # DW joins → dm.dm_steam_player_features_v1
```

---

## Quick start

1. **Run DDL first** — execute the SQL scripts before opening Spoon:
   - MSSQL: `../SQL/SQL_SQLServer_CreateStagingDB.sql`
   - Postgres: `../SQL/SQL_Postgres_InitWarehouse.sql`

2. **Configure DB connections** in Spoon (View → Database connections → New):
   | Name | Type | Host | Port | DB |
   |---|---|---|---|---|
   | `MSSQL_Staging` | MS SQL Server (Native) | localhost | 1433 | DW_Staging |
   | `Postgres_Warehouse` | PostgreSQL | localhost | 5432 | Warehouse |
   - Set `trustServerCertificate=true` on MSSQL connection.

3. **Open and run** `jobs/run_dss_refresh.kjb` in Spoon.

---

## Pipeline overview

```
Datasets/landing/extract_dt=.../
      │
      ▼
[00_validate_landing.kjb]       ← Finds newest unprocessed partition
      │
      ▼  (parallel)
[10_load_mssql_staging_*.ktr]   ← CSV → MSSQL stg_* tables (5 transforms)
      │
      ▼  (sequential)
[20_build_postgres_dw_*.ktr]    ← MSSQL stg → Postgres dw.* (4 transforms)
      │
      ▼
[30_build_datamart_features.ktr] ← dw.* joins → dm.dm_steam_player_features_v1
      │
      ▼
[Write audit log → dbo.stg_load_audit]
```

---

## Notes

- The **10x staging transforms** can run in **parallel** (independent target tables).
- The **20x DW transforms** must run **after all 10x complete** (sequential).
- `stg_load_audit` is the idempotency guard — the validation job skips already-loaded
  partitions by checking `WHERE status = 'success'`.
- `20_build_postgres_dw_fact_library.ktr` is the most complex transform — it explodes
  the `[appid1, appid2, ...]` list string into individual rows. Commit size is set to 5000.
- `review_duplication_rate` in the datamart feature table is currently a placeholder (= 0).
  Implement it by adding a deduplication subquery once review data matures.
