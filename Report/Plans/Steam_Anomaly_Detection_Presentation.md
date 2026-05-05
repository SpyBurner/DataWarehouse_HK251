# STEAM ANOMALY DETECTION
**Course:** C03135 | HK252 - P4DS&AI
**Institution:** BK TP.HCM
**Presenters:** Group Data 4 Life
**Instructors:** Huỳnh Văn Thống
**Date:** Ho Chi Minh, 15/4/2026

## Members & Roles
| FULL NAME | STUDENT ID | TASK ASSIGNED |
| :--- | :--- | :--- |
| Thịnh Trần Khánh Linh | 2211862 | ML Models, Evaluation |
| Trần Quang Tác | 2212962 | EDA, Visualization, Testing |

## Table of Contents
1. Introduction
2. Data Pipeline & EDA
3. Approach & Model Architecture
4. BI Dashboard & Testing
5. Conclusion

---

## 1. Introduction

[Image 1: Steam Cover Image]

**Fraud on Steam**
* **Achievement farming:** Using tools to unlock achievements in high speed, aiming to boost profile and sale account.
* **Review bombing:** Using networks of fake accounts to spam reviews and manipulate game ratings.

**Challenges**
* Unlabeled data.
* Tools designed to bypass detection.

**Objectives**
* Build a Machine Learning system that can detect anomalies based on history behavioral data of player (crawled via Steam API).
* Fill the detection gap of current Steam's VAC (Valve Anti Cheat) system.

---

## 2. Data Pipeline & EDA

[Image 2: ETL & Machine Learning Pipeline Diagram]

### Dataset
* **Gaming Profiles 2025 (Steam, PlayStation, Xbox) (Kaggle)**
* **Core Data Tables:**
    * `history` - user gaming activity for 2008-2025 (rows: 10,693,879; unique playerid: 4,838)
    * `players` - a list of Steam users (424k userID)
    * `private_steamids` - users with hidden profiles
    * `purchased_games` - a list of games purchased by each user (rows: 102,553)
    * `reviews` - user-submitted reviews for various games (rows: 1,204,534)

### ETL & Preprocessing
* **history Table:** Feature Selection, ID Extraction (Regex), Time Normalization, Privacy Filter, Deduplication.
* **players Table:** Type Casting, Privacy Filter, Deduplication.
* **reviews Table:** Type Casting, Privacy Filter, Deduplication.
* **purchased Table:** Data Parsing (List of Dicts), Feature Derivation (library_size), Privacy Filter, Deduplication.

### Player Coverage Across Datasets
* Players in history: 3,206
* Players in purchased: 49,844
* Players in reviews: 196,701
* Players in players.csv: 424,683
* Coverage history -> purchased: 100.00%
* Coverage purchased -> history: 6.43%

[Image 3: Player overlap count by dataset pair heatmap]

### Exploratory Data Analysis (EDA)

[Image 4: Histograms for log1p(Achievement count), log1p(Review count), log1p(Library size), log1p(Account age)]

**Question 1: Do specific account clusters exhibit anomalous achievement acquisition rates?**

[Image 5: Playtime per Achievement vs Achievement Volume Hexbin Density]

**Question 2: Are achievements diversely distributed across Libraries or heavily concentrated within a subset of games?**

[Image 6: Game Portfolio Concentration by User Segment bar charts]

**Question 3: What are the key behavioral pacing disparities between extreme user groups and the general user base?**

[Image 7: Hourly Line Chart (Circadian Rhythm Comparison)]

### Feature Engineering

**Group A - Speed Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 1 | median_unlock_interval_sec | The median time gap between consecutive achievement unlocks (identifies unnaturally fast progression). |
| 2 | std_unlock_interval_sec | Standard deviation of unlock intervals (measures absolute variability). |
| 3 | cv_unlock_interval | Coefficient of Variation (Std/Mean) - Measures behavioral consistency. Low CV indicates robotic, script-like regularity. |
| 4 | max_achievements_per_minute | Maximum achievements unlocked within a single minute |
| 5 | max_achievements_per_day | Peak achievements earned within 24 hours |

**Group B - Temporal Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 6 | total_achievements | Proportion of activity during late-night hours |
| 7 | library_size | Distribution entropy over 24 hours. |
| 8 | activity_density | Active days divided by total activity span. |

**Group C - Diversity Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 9 | total_achievements | Total volume of achievements earned across the account. |
| 10 | library_size | Total number of owned games |
| 11 | achievement_game_ratio | Ratio of games with achievements vs. total library size |
| 12 | top1_game_concentration | Percentage of achievements coming from the most-played game |
| 13 | top3_game_concentration | Combined percentage of achievements from the top 3 games. |
| 14 | game_hhi | Herfindahl-Hirschman Index - Measures whether achievements are diversified or hyper-concentrated in a few titles. |
| 15 | avg_achievements_per_game | Average achievements earned per active game. |

**Group D - Review Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 16 | total_reviews | Total number of reviews submitted. |
| 17 | review_unplayed_ratio | Ratio of reviews written for games with zero playtime |
| 18 | review_duplication_rate | Proportion of reviews with identical or near-identical content |
| 19 | avg_review_length | Average character count per review |
| 20 | min_review_length | The length of the shortest review submitted |

**Group E - Account Age Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 21 | days_before_first_achievement | Time elapsed between account creation and the first achievement |
| 22 | account_age_days | Total lifespan of the account in days |

**Group F - Playtime Plausibility Features**
| No | Metric | Mean / Description |
| --- | --- | --- |
| 23 | zero_playtime_achievements_ratio | Ratio of achievements earned with zero recorded playtime |
| 24 | playtime_per_achievement | Average minutes played required to earn one achievement |
| 25 | total_playtime_mins | Cumulative playtime across the entire library |

---

## 3. Approach & Model Architecture

* Static rules are simple to bypass and hard to detect complex behavioral data.
* ML models can find a baseline in N-dimension space → harder for cheaters to analyze and bypass in a short time.

**Algorithm Comparison**
| Thuật toán | Loại | Điểm mạnh | Điểm yếu |
| --- | --- | --- | --- |
| LOF | Unsupervised | Phát hiện local outlier tốt | $O(N^2)$ không scale được |
| One-Class SVM | Unsupervised | Phù hợp cho dữ liệu nhiều chiều, mất cân bằng | $O(N^2)$, nhạy cảm với noise |
| K-Means | Unsupervised | Nhanh, đơn giản | Không phù hợp cho dữ liệu mất cân bằng |
| Isolation Forest | Unsupervised | Phù hợp với dữ liệu lớn | Khó detect các loại bọt cụ thể |
| K-Nearest Neighbors | Unsupervised | Dễ implement | Không phù hợp cho dữ liệu lớn, mất cân bằng |
| XGBoost | Supervised | Dễ giải thích, phù hợp dữ liệu mất cân bằng | Cần dữ liệu có nhãn |

[Image 8: Dual Ensemble Machine Learning Diagram (XGBoost + Isolation Forest)]

### Dual Model
* Standard XGBoost requires fully labeled data.
* **PU-XGBoost:** Learn patterns from known bots (positive samples) and search for hidden bots in unlabeled data.
* Pseudo-labeling → heuristic bot + heuristic normal.
* **Isolation Forest:** Detect completely new anomaly patterns without relying on labels.
* Scores are normalized and combined into a final score.
* **Human-in-the-loop (Active Learning):** Detects conflicting cases → export for review. Feeds feedback back into the model to refine decision boundaries.

### Heuristic Rules
* **Trimming:** (≥10 achievements OR ≥3 reviews) AND library_size ≥ 1
* **Achievement bot:**
    * Speed: `median_unlock_interval_sec < 10s` AND `top1_game_concentration > 0.85`
    * Volume: (`max_per_day > 500` AND `night_activity_ratio > 0.40` AND `total_achievements > 1000`) OR `zero_playtime_achievements_ratio > 0.9`
* **Review bot:** `total_reviews > 5` AND `total_achievements < 5` AND `review_unplayed_ratio > 0.50` AND `review_duplication_rate > 0.50` AND `avg_rev_len < 50`
* **Normal:** `total_achievements > 10` AND `median_unlock_interval_sec > 600s`

### Tuning & Training
* **Isolation Forest:** grid search to maximize ROC-AUC → `best_if_params` → train.
* **XGBoost:** train on heuristic set to find `best_xgb` → predict for entire dataset.
* **Ensemble:** Sweep `xgb_weight` from 0.0 → 1.0 (step=0.05) to define optimal point maximizing Precision.

[Image 9: Ensemble Weight Sensitivity Analysis chart]

### Evaluating Method
* **Recall:** bot detected rate in real bots.
* **Precision:** correct rate of detected bots.
* **Accuracy:** correct detection rate for bots and normals.
* **F1-score:** balance evaluate between Precision and Recall at a threshold.
* **ROC-AUC:** trade-off between Recall and FPR → not helpful when bot << normal.
* **PR-AUC:** trade-off between Precision and Recall → not affected by large normal.
* **Precision@K:** correct rate of K detected bots.

### Evaluating Result (no HITL)
| Model | ROC-AUC | PR-AUC | Flagged Rate % | Precision@100 | Precision@500 | Precision@1000 |
| --- | --- | --- | --- | --- | --- | --- |
| XGBoost | 0.9050 | 0.7252 | 5.0525 | 1.00 | 0.602 | 0.324 |
| IsolationForest | 0.9882 | 0.5334 | 5.0038 | 0.64 | 0.524 | 0.405 |
| Ensemble | 0.9414 | 0.8354 | 7.7093 | 1.00 | 0.768 | 0.405 |

*Optimal threshold (F1): 0.9982*

**XGBoost Detailed Classification Report**
| Class | precision | recall | f1-score | support |
| --- | --- | --- | --- | --- |
| Normal | 0.99 | 1.00 | 1.00 | 22131 |
| Bot | 0.91 | 0.66 | 0.76 | 452 |
| **accuracy** | | | **0.99** | **22583** |
| **macro avg** | 0.95 | 0.83 | 0.88 | 22583 |
| **weighted avg** | 0.99 | 0.99 | 0.99 | 22583 |

[Image 10: XGBoost Feature Importance (Top 15) bar chart]
[Image 11: SHAP Model Explanation - SHAP values scatter plot]
[Image 12: SHAP Model Explanation - Waterfall plot]

---

## 4. BI Dashboard & Testing

### Steam Anomaly Detection Dashboard

[Image 13: Dashboard Interface - Search by Steam ID]

**1) Search by Steam ID**
* Enter a single ID, multiple IDs, or drag and drop a CSV/TXT file.
* Provides: Quick assessment, Probability, XGB percentile, IF percentile, Composite score, and detailed behavioral metrics compared to baseline.

[Image 14: Dashboard Details - View Details for playerid]

**2) Real-time Steam Crawl (Online Inference)**
* Baseline model: 2026-04-10 16:34:19 (Number of players in baseline: 3,154).
* Allows scoring profiles with trained model on the fly.
* Output: Assessment, Risk Level, Confidence, Anomaly Score, Normal Score.

[Image 15: Comparison with Baseline (Showing Top 12 Most Deviant Metrics per Player) chart]

**3) Data Overview and Insights**

[Image 16: Composite Score Distribution chart]

* Total Accounts in Baseline: 3,154
* Accounts Flagged: 390
* Normal: 2,764
* Flag Rate: 12.37%
* Average Anomaly Score: 50.02

[Image 17: Geographic Anomaly Distribution (Unique Countries: 158, Unknown Location Rate: 24.60%)]

[Image 18: Model Correlation & Ensemble Consensus dashboards]

[Image 19: Consensus Matrix: XGBoost vs. Isolation Forest]

**Behavioral Insights & Differentiation**
* Direct comparison between Flagged accounts (Anomaly) and Normal accounts.

**Top 10 Features by Separation Strength (Cohen's d)**
| Feature | Ratio (Bot/Normal) | Effect Size (Cohen's d) |
| --- | --- | --- |
| Activity Hour Entropy | 0.6039 | -2.665 |
| Unlock Interval CV | 3.5245 | 2.2679 |
| Max Achievements/Min | 28.3519 | 2.0719 |
| Avg Achievements/Game | 8.2995 | 1.67 |
| Top 1 Game Concentration | 2.025 | 1.2082 |
| Max Achievements/Day | 37.9441 | 1.1935 |
| Game Concentration Index (HHI) | 2.5023 | 1.1517 |
| Top 3 Games Concentration | 1.5594 | 0.9697 |
| Total Achievements | 10.8906 | 0.905 |
| Unlock Interval Std Dev | 0.283 | -0.5614 |

[Image 20: Mean Ratio (Flagged vs. Normal) and Statistical Effect Size bar charts]
[Image 21: Demographic & Behavioral Correlation charts - Account Age and Total Reviews]
[Image 22: Anomaly Rate by Library Size, Playtime/Achievement, and Account Creation Year charts]

### Test Dataset
* **Total Samples:** 40 profiles.
* **Normal Profiles (20):** Authentic Steam users with diverse gaming histories.
* **Anomaly Profiles (20):** Manually synthesized behaviors (Extreme speed, farming patterns).
* **Data Source:** `[test_data.csv]`

**Confusion Matrix**
| Actual \ Predicted | Predicted Positive | Predicted Negative |
| --- | --- | --- |
| **Actual Positive** | 17 (TP) | 3 (FN) |
| **Actual Negative** | 1 (FP) | 19 (TN) |

---

## 5. Conclusion

**Advantages & Limitations**
* **Strengths:**
    * Dynamic Duo architecture: balances detection power and false positives.
    * Explainable AI (SHAP): clear interpretation of model decisions.
* **Limitations:**
    * Data leakage → heuristic rules based on features that the model uses.
    * API Constraints: rate limits cause incomplete and inconsistent data.
    * Network Blindspot (Review Bots): hard to identify coordinated bot networks.
    * Dependence on Heuristic Labels: may require refinement if rules are biased.
* **Future Work:**
    * Graph-Based Detection (GNN): Model relationships between users, games, and reviews.
    * Use time-series models (LSTM/Transformer): capture complex behavioral patterns.
