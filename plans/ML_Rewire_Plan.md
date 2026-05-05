# ML Pipeline Rewire Agent Tasks

[problem] ML pipeline bypasses Data Warehouse and relies on standalone CSVs. → [cause] Reset to standalone state. → [fix] Rewire data_prep.py to fetch directly from Postgres DW schema.

## Batch 1: Environment Configuration
- [x] [problem] ML Pipeline lacks DB connection configuration. → [cause] Hardcoded CSV reads used previously. → [fix] Inject `DB_HOST=postgres-warehouse`, `DB_USER=postgres`, `DB_PASSWORD=31082004@Lmao`, `DB_NAME=Warehouse`, `DB_PORT=5432` into `ml-pipeline` and `ml-dashboard` services in `docker-compose.yml`.

## Batch 2: Data Fetching Integration
- [x] [problem] `data_prep.py` reads from raw/crawled CSVs. → [cause] Legacy standalone design. → [fix] Import SQLAlchemy in `data_prep.py`. Define database connection string using env variables. Replace `load_history`, `load_players`, `load_reviews`, `load_purchased` to execute SQL queries.

## Batch 3: Schema Mismatch Resolution
- [x] [problem] `purchased` data format mismatch. → [cause] ML Pipeline expects `library` as JSON list per player; DW stores it as normalized rows (`dw.fact_library`). → [fix] Modify `load_purchased` SQL query to use `SELECT playerid, json_agg(json_build_object('appid', appid, 'playtime_mins', playtime_mins))::text AS library FROM dw.fact_library GROUP BY playerid`.
- [x] [problem] `players` privacy filter mismatch. → [cause] ML Pipeline expects `private_steamids.csv` to filter. → [fix] Modify `load_players`, `load_history`, `load_reviews`, `load_purchased` SQL queries to join `dw.dim_player` and filter by `is_private = FALSE`. 

## Batch 4: Legacy Code Cleanup
- [x] [problem] Legacy CSV merging and filtering code bloats `data_prep.py`. → [cause] No longer needed after DB integration. → [fix] Remove `_merge_with_crawled`, `load_private_ids`, and CSV specific parsing logic (except `_parse_list_fast`).
