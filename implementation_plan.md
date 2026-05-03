# Fix Pentaho Feature Calculation Logic — Final

3 confirmed logic bugs. 1 suspected (needs manual check). All in feature calculation SQL.

---

## BUG-1: Branch F `total_playtime_mins` — wrong scope (CONFIRMED)

**Spec** (Data-pipeline.md line 94):
> `total_playtime_mins` = sum playtime of **Condition B** games only (in history AND library, playtime > 0, distinct per game)

**Pentaho SQL** (Branch F):
```sql
COALESCE(t.total_playtime_mins, SUM(l.playtime_mins)) AS total_playtime_mins
```

`total_play` CTE sums ALL `fact_library` playtime — every game player owns, not just achievement games. COALESCE picks `t` first (NOT NULL for any library-having player) → always uses wrong value.

**Fix**: Drop `total_play` CTE. Compute from joined rows only:
```sql
SUM(l.playtime_mins) FILTER (WHERE l.playtime_mins > 0) AS total_playtime_mins
```

Also verify `playtime_per_achievement` numerator stays consistent (currently `SUM(l.playtime_mins)` which includes playtime=0 rows — effectively same since 0 adds nothing, but should explicitly match).

---

## BUG-2: `hour_entropy` — log base (CONFIRMED)

**Spec**: Shannon entropy. Python `scipy.stats.entropy()` = natural log (nats).

**SQL** ([SQL_Postgres_InitWarehouse.sql](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/SQL/SQL_Postgres_InitWarehouse.sql) line 111):
```sql
entropy := entropy - (p * log(2.0, p));  -- base 2
```

**Fix**:
```diff
- entropy := entropy - (p * log(2.0, p));
+ entropy := entropy - (p * ln(p));
```

---

## BUG-3: Branch E `account_age_days` — NOW() (CONFIRMED)

**Spec** (Data-pipeline.md line 48): `feature_reference_time = max(date_acquired)`.

**Pentaho SQL** (Branch E):
```sql
TRUNC(EXTRACT(EPOCH FROM (NOW() - p.created)) / 86400) AS account_age_days
```

**Fix**:
```diff
- TRUNC(EXTRACT(EPOCH FROM (NOW() - p.created)) / 86400) AS account_age_days
+ TRUNC(EXTRACT(EPOCH FROM (
+   (SELECT MAX(date_acquired) FROM dw.fact_achievement_unlock) - p.created
+ )) / 86400) AS account_age_days
```

---

## BUG-4: Timestamp timezone shift — SUSPECTED

[20_build_postgres_dw_fact_history.ktr](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/Pentaho/transforms/20_build_postgres_dw_fact_history.ktr) Select Values step (line 690):
```xml
<conversion_mask>DD/MM/YYYY HH:mm</conversion_mask>
```
Pentaho field metadata (line 768):
```xml
<date_format_timezone>Asia/Saigon</date_format_timezone>
```

If raw timestamps are UTC, Pentaho's Java layer may interpret them as Asia/Saigon (UTC+7) then write to Postgres `TIMESTAMP` (no TZ) → stored times shifted. Branch B then adds country UTC offset on already-shifted data.

**Cannot confirm** — datasets don't overlap, so no row-level comparison possible.

**To verify**: Pick any player from your DW. Check if `EXTRACT(HOUR FROM date_acquired)` looks 7 hours ahead of what you'd expect from the raw CSV for that player's country. If yes → timezone shift during load. If no → just data difference.

**If confirmed, fix**: Remove `date_format_timezone` from the Select Values metadata, or set it explicitly to UTC.

---

## Files to Modify

| File | Change |
|------|--------|
| [SQL_Postgres_InitWarehouse.sql](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/SQL/SQL_Postgres_InitWarehouse.sql) | Line 111: `log(2.0, p)` → `ln(p)` |
| [30_build_datamart_features.ktr](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/Pentaho/transforms/30_build_datamart_features.ktr) | Branch E SQL: `NOW()` → `MAX(date_acquired)` subquery |
| [30_build_datamart_features.ktr](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/Pentaho/transforms/30_build_datamart_features.ktr) | Branch F SQL: remove `total_play` CTE, use filtered SUM |
| [20_build_postgres_dw_fact_history.ktr](file:///d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL%20DW/Pentaho/transforms/20_build_postgres_dw_fact_history.ktr) | **Only if BUG-4 confirmed**: fix timezone metadata |

---

## Verification

After fixes, re-run `30_build_datamart_features.ktr`, then re-run ML pipeline. Check:

```sql
-- Entropy should now use natural log (values roughly 0.693x of before)
SELECT playerid, hour_entropy FROM dm.dm_steam_player_features_v1 LIMIT 5;

-- account_age_days should be fixed reference, not growing daily
SELECT playerid, account_age_days FROM dm.dm_steam_player_features_v1 LIMIT 5;

-- total_playtime_mins should be <= previous values (only achievement games now)
SELECT playerid, total_playtime_mins FROM dm.dm_steam_player_features_v1
WHERE total_playtime_mins > 0 LIMIT 5;
```

Then compare `model_comparison.csv` — XGBoost ROC-AUC should no longer be 1.0 (that was overfitting to broken features).
