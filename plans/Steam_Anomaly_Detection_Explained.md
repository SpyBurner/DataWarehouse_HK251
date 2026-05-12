# Steam Anomaly Detection System — Full Explainer

> **Target audience:** Someone with no data-mining background who needs to understand the entire system, judge whether the ML output is correct, and read every chart it produces.

---

## 1. What This Repo Does

This project **detects cheating / bot accounts on the Steam gaming platform** using machine learning.

Steam is the world's largest PC gaming marketplace. Some accounts exhibit *abnormal behavior*:
- **Unlocking achievements impossibly fast** (using third-party tools like Steam Achievement Manager — "SAM")
- **Posting spam reviews** on games they never played
- **Running scripts 24/7** to farm achievements

The system ingests raw Steam data (player profiles, achievement history, game libraries, reviews), engineers 25 behavioral features per player, and trains an **ensemble of two ML models** (XGBoost + Isolation Forest) to flag suspicious accounts.

**Final output per player:** a `composite_score` from 0–100 (higher = more suspicious), plus a binary `is_anomaly` flag (`1` if score ≥ 85).

---

## 2. Input Tables & Data Flow (Per Table)

### Raw input files (in `data/raw/`)

| # | File | Size | Description |
|---|------|------|-------------|
| 1 | `players.csv` | ~18 MB | One row per Steam account: `playerid`, `country`, `created` (account creation timestamp) |
| 2 | `history.csv` | ~647 MB | One row per achievement unlock event: `playerid`, `achievementid` (format: `<gameid>_<name>`), `date_acquired` |
| 3 | `reviews.csv` | ~551 MB | One row per review: `reviewid`, `playerid`, `gameid`, `review` (text), `helpful`, `funny`, `awards`, `posted` |
| 4 | `purchased_games.csv` | ~92 MB | One row per player: `playerid`, `library` (JSON list of `{appid, playtime_mins}`) |
| 5 | `private_steamids.csv` | ~4 MB | List of private/hidden accounts to exclude |

### Additional reference files (used in BTL DW path only)

| # | File | Description |
|---|------|-------------|
| 6 | `achievements.csv` | Achievement metadata: `achievementid`, `gameid`, `title`, `description` |
| 7 | `games.csv` | Game metadata: `gameid`, `title`, `developers`, `publishers`, `genres`, `release_date` |
| 8 | `friends.csv` | Social graph (currently unused by ML pipeline) |
| 9 | `prices.csv` | Game pricing data (currently unused by ML pipeline) |

### Processing pipeline per table

#### `private_steamids.csv`
1. Read CSV → load into a Python `set` of player IDs
2. Used as a filter: all rows matching these IDs are **removed** from every other table

#### `history.csv` (achievement unlock events)
1. Read CSV (columns: `playerid`, `achievementid`, `date_acquired`)
2. **Merge crawled data** — if `data/crawled/history.csv` exists, append those rows in RAM (original file untouched)
3. **Handle column typo** — the raw CSV may have `date_accquired` (double 'c'): if found, merge values into `date_acquired` and drop the typo column
4. **Extract gameid** — regex `^(\d+)_` on `achievementid` → extract the numeric game ID prefix
5. **Parse timestamps** — convert `date_acquired` to datetime (format: `YYYY-MM-DD HH:MM:SS`)
6. **Remove private players** — filter out rows where `playerid ∈ private_ids`
7. **Deduplicate** — drop duplicates on `(playerid, achievementid, date_acquired)`, keep last
8. **Export** → `data/processed/history.parquet`

#### `players.csv` (account profiles)
1. Read CSV (columns: `playerid`, `country`, `created`)
2. Merge crawled data if available
3. Parse `created` timestamp
4. Remove private players
5. Deduplicate on `playerid`
6. **Export** → `data/processed/players.parquet`

#### `reviews.csv`
1. Read CSV (columns: `reviewid`, `playerid`, `gameid`, `review`, `helpful`, `funny`, `awards`, `posted`)
2. Merge crawled data
3. Parse `posted` as date
4. Remove private players
5. Deduplicate on `reviewid`
6. **Export** → `data/processed/reviews.parquet`

#### `purchased_games.csv` (game libraries)
1. Read CSV using **robust parser** (handles malformed rows with unescaped inner quotes)
2. Merge crawled data
3. **Parse library JSON** — each player's `library` field is a JSON string:
   - Old format: `[10, 20, 30]` → converted to `[{appid: 10, playtime_mins: -1}, ...]` (`-1` means "no playtime data")
   - New format: `[{appid: 10, playtime_mins: 0}, ...]` → used directly
4. Add `library_size` = number of games owned
5. Remove private players
6. Deduplicate on `playerid`
7. **Export** → `data/processed/purchased.parquet`

---

## 3. Feature Engineering — All 25 Features Explained

After loading parquets, the system computes 25 features per player. Before computing features, a **trimming** step reduces the working set:

**Trimming criteria:** `(≥10 achievements OR ≥3 reviews) AND library_size ≥ 1`
- This drops ~98% of accounts (ghost/inactive accounts with almost no activity)
- The OR logic keeps "review bots" who have 0 achievements but spam reviews
- Roughly **196k → ~3k players** remain (the current code comment says ~22k in the README)

### Group A — Speed Features (5 features)

These measure *how fast* a player unlocks achievements. Bots often unlock hundreds per second.

| Feature | Calculation | What it means (plain English) |
|---------|------------|------------------------------|
| `median_unlock_interval_sec` | Median of time gaps between consecutive achievement unlocks for this player (in seconds) | The "typical" waiting time between two unlocks. Real players: hundreds to thousands of seconds. Bots: often < 10 seconds. |
| `std_unlock_interval_sec` | Standard deviation of those time gaps | How *variable* the unlock timing is. Bots using scripts tend to have very uniform timing → low std. |
| `cv_unlock_interval` | `std / mean` (coefficient of variation) | A normalized measure of timing variability. CV < 1 with many achievements = very suspicious (machine-like regularity). |
| `max_achievements_per_minute` | Take all achievements, bucket by minute, find the max bucket size | The highest burst of achievements ever achieved in a single minute. Humans rarely exceed 3–5; bots can hit 60+. |
| `max_achievements_per_day` | Same logic but bucketed by calendar day | Highest single-day count. Normal players: 10–50. Volume bots: > 500. |

### Group B — Temporal Features (3 features)

These analyze *when* a player is active. Bots often run overnight (local time).

| Feature | Calculation | What it means |
|---------|------------|---------------|
| `night_activity_ratio` | Fraction of achievements unlocked between 00:00–05:59 **local time** (timezone-adjusted using `country` field from `players`) | High values (> 40%) suggest automated scripts running while the real user sleeps. A normal gamer might have 10–15%. |
| `hour_entropy` | Shannon entropy of the 24-hour distribution of unlock times (local time) | Measures how "spread out" activity is across the day. High entropy = activity spread across many hours (normal). Low entropy = concentrated in a few hours (could be a bot running at specific times). Formula: `-Σ(p × ln(p))` where `p` = fraction of events in each hour. Max value ≈ 3.18 (perfectly uniform). |
| `activity_density` | `active_days / calendar_span` (first to last achievement date) | If a player was active for 5 days out of a 365-day span, density = 0.014. High density = concentrated burst of activity. Normal gamers have moderate density (they play regularly but not every day). |

### Group C — Diversity Features (7 features)

These measure *how many games* a player engages with and how concentrated their activity is.

| Feature | Calculation | What it means |
|---------|------------|---------------|
| `total_achievements` | Count of all achievement unlock events | Raw activity volume. Very high values with fast timing = bot. |
| `library_size` | Number of games the player owns | From the `purchased_games` library. Some bots own many cheap games. |
| `achievement_game_ratio` | `games_with_achievements / library_size` | What fraction of owned games has the player actually earned achievements in. Low ratio = owns many games but only bots achievements in a few. |
| `top1_game_concentration` | Fraction of all achievements that come from the single most-played game | If > 85%, most activity is in one game — typical of speed bots focusing on one easy-to-exploit game. |
| `top3_game_concentration` | Fraction from the top 3 games | Similar to above but broader. |
| `game_hhi` | Herfindahl-Hirschman Index = `Σ(proportion²)` for each game | A standard economics measure of concentration. HHI = 1.0 means all achievements are in one game. HHI close to 0 means spread across many games. |
| `avg_achievements_per_game` | `total_achievements / games_with_achievements` | How many achievements per game on average. Very high values suggest grinding or botting specific games. |

### Group D — Review Features (5 features)

These detect "review bots" — accounts that post spam reviews for games they never played.

| Feature | Calculation | What it means |
|---------|------------|---------------|
| `total_reviews` | Count of reviews posted by this player | The raw review volume. |
| `review_unplayed_ratio` | Fraction of reviews posted for games where `playtime_mins == 0` in the player's library | If > 50%, the player is reviewing games they never launched. Strong bot signal. |
| `review_duplication_rate` | `1 - (unique_review_texts / total_reviews)` | How much the player copy-pastes the same review. > 50% = very suspicious. |
| `avg_review_length` | Mean character count of all reviews | Bot reviews tend to be very short (< 50 characters). |
| `min_review_length` | Shortest review character count | If even the shortest review is > 100 chars, more likely a real reviewer. |

### Group E — Account Age Features (2 features)

| Feature | Calculation | What it means |
|---------|------------|---------------|
| `days_before_first_achievement` | `first_achievement_date - account_created_date` (days, clipped to ≥ 0) | How long the account existed before earning its first achievement. Bot accounts sometimes start botting immediately (low value) or are dormant for years then suddenly activate. |
| `account_age_days` | `reference_time - account_created_date` | Total age of the account. `reference_time` is the timestamp of the latest achievement in the entire dataset (used as a fixed reference point). |

### Group F — Playtime Features (3 features)

These compare achievements against actual game playtime — the signature of SAM (Steam Achievement Manager).

| Feature | Calculation | What it means |
|---------|------------|---------------|
| `zero_playtime_achievements_ratio` | `C / (B + C)` where B = achievements on games with playtime > 0, C = achievements on games with playtime == 0 (both must be in the player's library) | The "SAM detector." If > 90%, the player earned almost all achievements on games they *own* but *never launched* — the exact fingerprint of SAM. |
| `total_playtime_mins` | Sum of `playtime_mins` across distinct Condition B games | Total actual gameplay time. |
| `playtime_per_achievement` | `total_playtime_mins / (B + C)` | Minutes of gameplay per achievement earned. Very low values = unlocking achievements without actually playing. |

**Important detail about the playtime logic:**
- **Condition A (excluded):** Game appears in achievement history but NOT in the player's library → API lag artifact → silently excluded
- **Condition B (normal):** Game in library with `playtime_mins > 0` → real gameplay
- **Condition C (suspicious):** Game in library with `playtime_mins == 0` → owned but never launched, yet has achievements

---

## 4. Heuristic Labels (Pseudo Ground Truth)

Since there's **no real labeled dataset** (Steam doesn't publish which accounts are bots), the system creates **heuristic labels** — rule-based "best guesses" — to serve as training targets.

### Bot archetypes

| Bot Type | Rule (ALL conditions must be true) | What it catches |
|----------|-----------------------------------|-----------------|
| **Speed Bot** | `median_unlock_interval_sec < 10` AND `top1_game_concentration > 0.85` | Players unlocking achievements faster than humanly possible, focused on one game |
| **Volume Bot** | (`max_achievements_per_day > 500` AND `night_activity_ratio > 0.40` AND `total_achievements > 1000`) OR `zero_playtime_achievements_ratio > 0.9` | Either massive nighttime grinding, or the "SAM catch-all" — 90%+ achievements on unplayed games |
| **Review Bot** | `total_reviews > 5` AND `total_achievements < 5` AND `review_unplayed_ratio > 0.50` AND `review_duplication_rate > 0.50` AND `avg_review_length < 50` | Accounts that only post short, duplicated reviews on games they never played |

> **Difference from Data-pipeline.md:** The current code uses `total_achievements < 5` instead of `== 0` for review bots — slightly broader catch. Also, the `avg_review_length < 50` condition is added (not in the original doc).

### Normal label (for PU Learning)
- `total_achievements > 10` AND `median_unlock_interval_sec > 600` (10 minutes)
- These are "confidently normal" players used as the negative class in training

### Active Learning (Human-in-the-Loop)
The system supports overriding these heuristic labels with human judgments via `data/reviewed.csv`. However, this is **currently commented out** in `main.py`.

---

## 5. Algorithms Used to Score Users

### Architecture: "Dynamic Duo" Ensemble

Two models are trained and combined:

```
Raw Features (25)
       │
       ├──────────────────┐
       │ Path A            │ Path B
       │ IsolationForest   │ XGBoost
       │                   │
       │ 1. log1p(9 cols)  │ 1. Use raw features
       │ 2. Impute median  │    (NaN = real signal)
       │ 3. StandardScaler │ 2. No imputation
       │                   │ 3. No scaling
       ↓                   ↓
  IsolationForest      XGBoost (PU Learning)
  (unsupervised)       (semi-supervised)
       ↓                   ↓
  Percentile Rank      Percentile Rank
  (0–100)              (0–100)
       ↓                   ↓
       └────────┬──────────┘
                ↓
    composite = 0.65 × xgb_pct + 0.35 × if_pct
                ↓
    is_anomaly = (composite ≥ 85) ? 1 : 0
```

> **Difference from Data-pipeline.md:** The doc says `0.70 × xgb + 0.30 × if`, but the **current code** in `models.py` line 318 uses **`0.65 × xgb + 0.35 × if`**. This is a meaningful difference that affects the final scores.

### Algorithm 1: Isolation Forest (Secondary, weight 0.35)

**What it is:** An *unsupervised* anomaly detection algorithm. It builds random decision trees that try to "isolate" each data point. Anomalies are easier to isolate (shorter path in the tree), so they get higher anomaly scores.

**Key concepts for understanding:**
- **Unsupervised** = doesn't need labels. It just looks for "unusual" patterns.
- **Path length** = how many splits it takes to isolate a point. Shorter = more anomalous.
- **Why log-transform:** Features like `std_unlock_interval_sec` span from 1 to 10,000,000+ seconds. Without compression, random splits mostly land in the sparse tail, making path lengths meaningless. `log1p` compresses the range.
- **Hyperparameter tuning:** Grid search over `n_estimators` (100/200/300), `max_samples`, `contamination` (expected fraction of anomalies: 2%/5%/10%), `max_features`. Best params chosen by ROC-AUC against heuristic labels.

### Algorithm 2: XGBoost with PU Learning (Primary, weight 0.65)

**What it is:** A *supervised* gradient boosting classifier, but trained using **Positive-Unlabeled (PU) Learning** because we only have noisy heuristic labels, not true labels.

**Key concepts:**
- **PU Learning:** Only trains on "confident" examples:
  - Positives = `heuristic_bot == 1` (clearly suspicious accounts)
  - Negatives = `heuristic_normal == 1` (clearly normal accounts)
  - Grey area = skipped entirely (avoids learning from uncertain labels)
- **`scale_pos_weight`** = `neg_count / pos_count` — automatically balances the class imbalance (many more normals than bots)
- **RandomizedSearchCV** with 50 iterations, 5-fold cross-validation, scored by **PR-AUC** (Precision-Recall Area Under Curve)
- **NaN handling:** XGBoost handles missing values natively — NaN in review features (for players with no reviews) is an *informative signal*, not noise to fill

### Ensemble combination

Both models output raw scores on different scales:
- IF outputs negative path lengths (more negative = more anomalous)
- XGBoost outputs probabilities (0–1)

These are incomparable, so both are converted to **percentile ranks** (0–100) within the training population, then combined with a weighted average.

---

## 6. Knowledge Needed to Judge Results

### How to tell if a result is correct

1. **Check the composite_score against the player's features.** Open `feature_matrix.csv`, find the player by `playerid`, and manually verify:
   - If `median_unlock_interval_sec` < 10 and they have high concentration → speed bot signal ✓
   - If `zero_playtime_achievements_ratio` > 0.9 → SAM bot signal ✓
   - If `review_duplication_rate` > 0.5 with many reviews → review bot signal ✓

2. **Check for "High-Conflict Cases"** in the output. These are players where:
   - The ML model says "anomaly" (`composite_score ≥ 85`)
   - But the heuristic rules say "normal" (`heuristic_bot == 0`)
   - These are the most interesting cases — potential "stealth bots" the rules missed

3. **Look at the model comparison table** (`model_comparison.csv`):
   - **ROC-AUC** > 0.7 is acceptable, > 0.8 is good
   - **PR-AUC** is more important for imbalanced data — even 0.3 can be reasonable when bots are < 5% of the population
   - **Precision@100** = "if you manually check the top 100 flagged accounts, what % are actually bots?" Higher is better

4. **Known limitation — target leakage:** The heuristic labels are computed from the same features used to train the model. This means **the model is partially just learning to mimic the rules**, not truly discovering new patterns. The evaluation metrics are therefore **upper bounds** on real-world performance.

### Key statistical concepts you need

| Concept | Plain English |
|---------|--------------|
| **ROC-AUC** | "How well can the model distinguish bots from normals across all possible thresholds?" 1.0 = perfect, 0.5 = random guess. |
| **PR-AUC** | Same idea but focuses on the *positive class* (bots). Better metric when bots are rare (< 5%). |
| **Precision@K** | "If I check the top K flagged players, how many are actually bots?" This is the most practical metric. |
| **Percentile rank** | Player's score relative to everyone else. "95th percentile" = more suspicious than 95% of players. |
| **Shannon entropy** | Measures randomness/spread. High entropy = activity spread across many hours (looks human). Low entropy = concentrated (could be bot). |
| **Herfindahl Index (HHI)** | Measures concentration. HHI = 1.0 = all eggs in one basket. HHI near 0 = diverse. |
| **Coefficient of Variation (CV)** | `std / mean`. Normalizes variability. Low CV = very regular (machine-like). |
| **Cohen's d** | Effect size between two groups. |d| > 0.8 = large difference. Used in the Streamlit dashboard to compare flagged vs. normal players. |
| **SHAP values** | "How much did each feature contribute to this player's score?" Positive SHAP = pushed toward "bot". Negative = pushed toward "normal". |

---

## 7. Charts Generated & How to Read Them

### 7.1 Training Pipeline Charts (in `outputs/plots/`)

#### `xgb_pr_curve.png` — Precision-Recall Curve (XGBoost)
- **X-axis:** Recall (what fraction of actual bots did we catch?)
- **Y-axis:** Precision (of the ones we flagged, how many were actually bots?)
- **Blue curve:** The trade-off as you vary the classification threshold
- **Red dashed line:** The "optimal" threshold that maximizes F1 score (harmonic mean of precision and recall)
- **PR-AUC value** shown in the legend — higher is better
- **How to judge:** A curve that stays high and to the right is good. If it drops sharply, the model struggles to maintain precision as it tries to catch more bots.

#### `xgb_feature_importance.png` — Top 15 Feature Importance (XGBoost)
- **Horizontal bar chart** showing which features XGBoost relies on most
- **Higher bar = more important** for the model's decisions
- **How to judge:** The top features should make intuitive sense (e.g., `median_unlock_interval_sec`, `zero_playtime_achievements_ratio`). If a random/unrelated feature ranks #1, something may be wrong.

#### `shap_summary.png` — SHAP Global Feature Importance
- **Dot plot** where each dot = one player
- **X-axis:** SHAP value (positive = pushes toward "bot", negative = toward "normal")
- **Color:** Feature value (red = high, blue = low)
- **Y-axis:** Features sorted by importance (most impactful at top)
- **How to read:** For example, if `median_unlock_interval_sec` shows blue dots (low values) on the right (positive SHAP), it means low unlock intervals push the prediction toward "bot" — which makes sense.

#### `shap_waterfall.png` — Single Player SHAP Breakdown
- Shows the feature-by-feature contribution for **the most suspicious player** in a sample of 5000
- **Base value** (average prediction) on the left, final prediction on the right
- Each bar shows how much that feature pushed the prediction up (toward bot) or down (toward normal)
- **How to judge:** You should see features like `median_unlock_interval_sec` or `zero_playtime_ratio` pushing strongly toward "bot".

#### `shap_scatter_<feature>.png` — SHAP Scatter Plots (top 3 features)
- **X-axis:** Raw feature value
- **Y-axis:** SHAP value (contribution to prediction)
- Shows how the model uses each feature across different values
- **How to judge:** You should see a clear relationship (e.g., lower `median_unlock_interval_sec` → higher SHAP value → more suspicious).

#### `ensemble_weight_tuning.png` — Weight Sensitivity Analysis
- **Dual-axis chart** analyzing the XGBoost vs IF weight split
- **Left axis (blue line):** Precision@100 as XGB weight varies from 0 to 1
- **Left axis (green line):** PR-AUC
- **Right axis (red dashed):** High-Conflict Cases count (stealth bots)
- **Orange dashed vertical:** The "optimal" XGB weight
- **How to judge:** The optimal point balances high precision (we want flagged players to actually be bots) with enough stealth bot detection (we don't want to miss unusual bots the heuristics don't catch).

### 7.2 Streamlit Dashboard Charts

The interactive dashboard (`streamlit_app.py`) generates additional visualizations per queried player:

- **Risk Score Gauge** — donut chart showing composite_score with color coding (green < 40, yellow 40–65, orange 65–85, red ≥ 85)
- **Model Agreement Matrix** — shows `(xgb_flag, if_flag)` combinations:
  - `(1,1)` = both models agree it's anomalous
  - `(1,0)` = only XGBoost flags it
  - `(0,1)` = only IF flags it
  - `(0,0)` = neither model flags it
- **Feature Comparison Bars** — per-feature bar chart comparing the queried player's value to the baseline (normal users) median/percentile
- **Behavior Reference Table** — Cohen's d effect sizes showing which features most differentiate flagged from normal accounts

---

## 8. Differences Between Current Code and Data-pipeline.md

The `Data-pipeline.md` document is **mostly accurate** but has several outdated details:

| Aspect | Data-pipeline.md says | Current code actually does |
|--------|----------------------|---------------------------|
| **Ensemble weights** | `0.70 × xgb_pct + 0.30 × if_pct` | `0.65 × xgb_pct + 0.35 × if_pct` (models.py line 318) |
| **Review bot condition** | `total_achievements == 0` | `total_achievements < 5` (features.py line 162) |
| **Review bot avg_review_length** | `avg_rev_len < 50` mentioned | Present in current code (features.py line 165) — consistent |
| **Feature count** | "25 features" | 25 features — still accurate |
| **Active Learning** | Described as active workflow | **Commented out** in main.py (lines 98–99 and 163) — not used in production runs |
| **Streamlit composite weight** | Not mentioned | Streamlit's `infer_online_profiles_batch()` uses `0.70 × xgb + 0.30 × if` — **different from** the training pipeline's `0.65/0.35` |
| **data_prep `date_accquired` handling** | Not mentioned | Code handles the typo column `date_accquired` → merged into `date_acquired` |

---

## 9. Complete Pipeline Execution Flow

```
Step 0: Data Preparation (src/data_prep.py)
    CSV files → clean → deduplicate → Parquet files
    ↓
Step 1: Load Parquets (main.py)
    Read 4 parquet files into DataFrames
    Add time components (hour, day_of_week, date_only)
    ↓
Step 2: Feature Engineering (features.py → build_feature_matrix)
    Trimming → 6 feature groups (A-F) → 25 features per player
    ↓
Step 3: Heuristic Labels (features.py → build_heuristic_labels)
    Apply 3 bot-type rules + 1 normal rule → pseudo ground truth
    ↓
Step 4: Preprocessing Path A (models.py)
    log1p(9 cols) → SimpleImputer(median) → StandardScaler → X_if
    ↓
Step 5a: Tune IF (models.py → tune_models)
    Grid search over 54 parameter combos → best_if_params
    ↓
Step 5b: Train XGBoost (models.py → train_xgboost_semisupervised)
    PU Learning on confident subset → RandomizedSearch(50 iter, 5-fold CV)
    ↓
Step 6: Train Final IF (models.py → train_best_models)
    Retrain IF with best params on full data
    ↓
Step 7: Ensemble (models.py → build_ensemble)
    Percentile rank both → weighted combine → is_anomaly flag
    ↓
Step 7b: Ensemble Weight Tuning (analysis only)
    Sweep weights 0→1 → find optimal balance
    ↓
Step 8: Evaluation (evaluate.py)
    Model comparison table, PR curve, feature importance
    ↓
Step 9: SHAP Explanations (evaluate.py → _shap_plots)
    Summary plot, waterfall, scatter plots for top 3 features
    ↓
Output: All results + models + charts saved to outputs/
```

---

## 10. Output Files Reference

| File | Contents |
|------|----------|
| `feature_matrix.csv` | 25 raw features for all active players (index = playerid) |
| `heuristic_labels.csv` | `heuristic_bot` and `heuristic_normal` columns per player |
| `ensemble_results.csv` | Final scores: `playerid`, `composite_score`, `is_anomaly`, `xgb_proba`, `xgb_pct`, `if_pct`, `xgb_flag`, `if_flag`, `heuristic_bot` |
| `model_comparison.csv` | ROC-AUC, PR-AUC, Flagged Rate%, Precision@K for all 3 models |
| `ensemble_weight_metrics.csv` | Precision@100, PR-AUC, HCC at each weight point |
| `top50_flagged_profiles.csv` | Mean features of top-50 flagged vs normal players |
| `tuning_results.csv` | IF grid search results |
| `xgb_tuning_results.csv` | XGBoost RandomizedSearch CV results |
| `best_xgb.pkl` | Trained XGBoost model |
| `best_if.pkl` | Trained Isolation Forest model |
| `preprocessor.pkl` | Fitted SimpleImputer + StandardScaler pipeline (for IF path) |
| `model_memory.pkl` | Calibration data for online scoring (sorted baselines, feature column order) |
| `plots/*.png` | All visualization charts (see Section 7) |
