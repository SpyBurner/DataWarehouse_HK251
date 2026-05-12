# Model Performance Divergence Analysis: Python Pipeline vs. Pentaho DW Pipeline

> **Date:** 2026-05-13  
> **Question:** Why does the new Pentaho DW pipeline show a different XGBoost precision and Flagged Rate compared to the old Python-exclusive pipeline?

---

## The Numbers

| Metric | Pentaho DW (New) | Python Script (Old) | Delta |
|--------|------------------|---------------------|-------|
| **XGBoost ROC-AUC** | 0.9952 | 0.8567 | +0.14 |
| **XGBoost PR-AUC** | 0.9899 | 0.5673 | +0.42 |
| **XGBoost P@500** | 1.0 | 0.438 | +0.56 |
| IF ROC-AUC | 0.9054 | 0.9597 | -0.05 |
| IF PR-AUC | 0.6228 | 0.7287 | -0.11 |

---

## Root Cause: `playtime_mins` SQL Bug

The entire performance gap traces to **172 players** whose `zero_playtime_achievements_ratio` evaluated to:
- **Pentaho DW Pipeline (New):** `1.0` (treated as "100% of achievements on zero-playtime games")
- **Python Pipeline (Old):** `NaN` (missing data, correctly ignored)

### How This Cascades

```
Private accounts have 'NaN' or missing playtime in the raw JSON
    ↓
Pentaho SQL job 'build_dw_bridge_fact_phase.kjb' used COALESCE(..., 0)
    ↓
Unknown playtimes were incorrectly forced to 0 minutes
    ↓
Heuristic labeling: volume_bot rule triggered incorrectly (zp_ratio > 0.9)
    ↓
Pentaho falsely labeled 153 normal/private users as SAM Unlocker bots
    ↓
XGBoost trained on corrupted ground truth, artificially inflating its metrics 
by successfully "predicting" these false positives.
```

### Verification

| Stat | Pentaho DW | Python Script |
|------|------------|---------------|
| `zp_ratio` NaN count | 784 | 956 |
| `zp_ratio == 1.0` count | 461 | 289 |
| `zp_ratio > 0.9` count | 461 | 289 |
| **heuristic_bot = 1** | **600 (18.1%)** | **461 (13.9%)** |

All 153 extra bots in the new Pentaho pipeline were triggered **exclusively** by the volume bot rule's `zp_ratio > 0.9` catch-all. None were triggered by speed or review rules.

---

## Why This Happens

When the Steam API crawls private accounts (or accounts that hide game details), the resulting JSON library data might contain games with missing or `'NaN'` `playtime_mins`. 

In the **old Python-exclusive pipeline**, missing playtime evaluated to `NaN`. The feature engineering script correctly ignored these games when computing `zero_playtime_achievements_ratio`.

In the **Pentaho DW pipeline**, the `build_dw_bridge_fact_phase.kjb` job had a flaw in its SQL unnesting logic:
```sql
CASE 
    WHEN json_typeof(game_element) = 'object' THEN COALESCE((game_element->>'playtime_mins')::int, 0)
    ELSE 0 
END as playtime_mins
```
The `COALESCE(..., 0)` forcefully converted missing/NaN playtime into `0`. 
Consequently, the pipeline saw these users earning achievements on games with "0 playtime" and incorrectly flagged them as SAM Unlockers (tools that unlock achievements without launching the game).

---

## Conclusion

| Aspect | Verdict |
|--------|---------|
| Is Pentaho's higher precision valid? | **No** — it is an artifact of corrupted ground truth labels. |
| Root cause | A SQL `COALESCE` bug converted missing playtime into `0` playtime. |
| The Fix | The SQL in `build_dw_bridge_fact_phase.kjb` has been updated to use `NULLIF` and insert `NULL` instead of defaulting to `0` for missing playtimes. |
| Next Steps | Rebuild the Data Warehouse facts and retrain the models to get accurate metrics. |
