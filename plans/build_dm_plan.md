Here is the complete, structured implementation plan designed specifically to be fed into an AI coding agent. It provides the exact SQL scripts and Pentaho architectural instructions required to execute Path A (Database Pushdown).

You can copy and paste everything below the line directly to your agent.

---

### **System Prompt / Execution Plan: Steam DW and Pentaho Datamart Refactoring**

**Objective:** Refactor the PostgreSQL Data Warehouse (DW) initialization scripts and the Pentaho Data Integration (PDI) transformations to calculate 26 player features natively in the database, avoiding in-memory Pentaho bottlenecks.

Please execute the following phases:

#### **Phase 1: Update DW Initialization (`dw_init.sql`)**
Modify the database schema and add the necessary mathematical functions for feature calculation.

2.  **Create Shannon Entropy Function:** Inject this PL/pgSQL function to calculate the 24-hour entropy distribution natively.
    ```sql
    CREATE OR REPLACE FUNCTION dw.calculate_shannon_entropy(hour_counts INT[])
    RETURNS NUMERIC AS $$
    DECLARE
        total_events INT := 0;
        entropy NUMERIC := 0.0;
        p NUMERIC;
        c INT;
    BEGIN
        -- Calculate total events
        FOREACH c IN ARRAY hour_counts LOOP
            total_events := total_events + COALESCE(c, 0);
        END LOOP;

        IF total_events = 0 THEN
            RETURN 0.0;
        END IF;

        -- Calculate Shannon entropy: -Sum(p * log2(p))
        FOREACH c IN ARRAY hour_counts LOOP
            IF c > 0 THEN
                p := c::NUMERIC / total_events;
                entropy := entropy - (p * log(2.0, p));
            END IF;
        END LOOP;

        RETURN ROUND(entropy, 4);
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    ```

#### **Phase 3: Build the Datamart Transformation (`dm_steam_player_features_v1`)**
Design the Pentaho transformation using a "Parallel Branching" architecture. Create six parallel **Table Input** steps (one for each feature group). Each Table Input will execute a heavy SQL aggregation grouping by `playerid`.

Use the following SQL queries for the respective Table Input steps:

**Branch A: Speed Features**
```sql
WITH intervals AS (
    SELECT playerid,
           EXTRACT(EPOCH FROM (date_acquired - LAG(date_acquired) OVER (PARTITION BY playerid ORDER BY date_acquired))) AS interval_sec,
           date_trunc('minute', date_acquired) as acq_minute,
           date_trunc('day', date_acquired) as acq_day
    FROM dw.fact_achievement_unlock
),
minute_counts AS (
    SELECT playerid, acq_minute, COUNT(*) as cnt FROM intervals GROUP BY playerid, acq_minute
),
day_counts AS (
    SELECT playerid, acq_day, COUNT(*) as cnt FROM intervals GROUP BY playerid, acq_day
)
SELECT 
    i.playerid,
    COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY interval_sec), 0) AS median_unlock_interval_sec,
    COALESCE(stddev_pop(interval_sec), 0) AS std_unlock_interval_sec,
    CASE WHEN avg(interval_sec) > 0 THEN stddev_pop(interval_sec) / avg(interval_sec) ELSE 0 END AS cv_unlock_interval,
    (SELECT MAX(cnt) FROM minute_counts m WHERE m.playerid = i.playerid) AS max_achievements_per_minute,
    (SELECT MAX(cnt) FROM day_counts d WHERE d.playerid = i.playerid) AS max_achievements_per_day
FROM intervals i
GROUP BY i.playerid
ORDER BY i.playerid;
```

**Branch B: Temporal Features**
```sql
WITH local_hours AS (
    SELECT 
        u.playerid,
        u.date_acquired,
        -- Assuming dim_player has a 'utc_offset' integer column
        MOD((EXTRACT(HOUR FROM u.date_acquired)::INT + COALESCE(p.utc_offset, 0) + 24), 24) AS local_hour
    FROM dw.fact_achievement_unlock u
    LEFT JOIN dw.dim_player p ON u.playerid = p.playerid
)
SELECT 
    playerid,
    COUNT(*) FILTER (WHERE local_hour < 6)::NUMERIC / NULLIF(COUNT(*), 0) AS night_activity_ratio,
    dw.calculate_shannon_entropy(
        ARRAY[
            COUNT(*) FILTER (WHERE local_hour = 0)::INT, COUNT(*) FILTER (WHERE local_hour = 1)::INT,
            COUNT(*) FILTER (WHERE local_hour = 2)::INT, COUNT(*) FILTER (WHERE local_hour = 3)::INT,
            COUNT(*) FILTER (WHERE local_hour = 4)::INT, COUNT(*) FILTER (WHERE local_hour = 5)::INT,
            COUNT(*) FILTER (WHERE local_hour = 6)::INT, COUNT(*) FILTER (WHERE local_hour = 7)::INT,
            COUNT(*) FILTER (WHERE local_hour = 8)::INT, COUNT(*) FILTER (WHERE local_hour = 9)::INT,
            COUNT(*) FILTER (WHERE local_hour = 10)::INT, COUNT(*) FILTER (WHERE local_hour = 11)::INT,
            COUNT(*) FILTER (WHERE local_hour = 12)::INT, COUNT(*) FILTER (WHERE local_hour = 13)::INT,
            COUNT(*) FILTER (WHERE local_hour = 14)::INT, COUNT(*) FILTER (WHERE local_hour = 15)::INT,
            COUNT(*) FILTER (WHERE local_hour = 16)::INT, COUNT(*) FILTER (WHERE local_hour = 17)::INT,
            COUNT(*) FILTER (WHERE local_hour = 18)::INT, COUNT(*) FILTER (WHERE local_hour = 19)::INT,
            COUNT(*) FILTER (WHERE local_hour = 20)::INT, COUNT(*) FILTER (WHERE local_hour = 21)::INT,
            COUNT(*) FILTER (WHERE local_hour = 22)::INT, COUNT(*) FILTER (WHERE local_hour = 23)::INT
        ]
    ) AS hour_entropy,
    COUNT(DISTINCT date_trunc('day', date_acquired))::NUMERIC / 
        NULLIF(EXTRACT(DAY FROM (MAX(date_acquired) - MIN(date_acquired))) + 1, 0) AS activity_density
FROM local_hours
GROUP BY playerid
ORDER BY playerid;
```

**Branch C: Diversity Features**
```sql
WITH base_stats AS (
    SELECT 
        u.playerid,
        COUNT(u.appid) AS total_achievements,
        COUNT(DISTINCT u.appid) AS games_with_achievements,
        (SELECT COUNT(*) FROM dw.fact_library l WHERE l.playerid = u.playerid) AS library_size
    FROM dw.fact_achievement_unlock u
    GROUP BY u.playerid
),
game_props AS (
    SELECT 
        playerid,
        COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY playerid), 0)::NUMERIC as prop,
        ROW_NUMBER() OVER (PARTITION BY playerid ORDER BY COUNT(*) DESC) as rnk
    FROM dw.fact_achievement_unlock
    GROUP BY playerid, appid
)
SELECT 
    b.playerid,
    b.total_achievements,
    b.games_with_achievements,
    b.library_size,
    b.games_with_achievements::NUMERIC / NULLIF(b.library_size, 0) AS achievement_game_ratio,
    b.total_achievements::NUMERIC / NULLIF(b.games_with_achievements, 0) AS avg_achievements_per_game,
    SUM(g.prop) FILTER (WHERE g.rnk = 1) AS top1_game_concentration,
    SUM(g.prop) FILTER (WHERE g.rnk <= 3) AS top3_game_concentration,
    SUM(POWER(g.prop, 2)) AS game_hhi
FROM base_stats b
LEFT JOIN game_props g ON b.playerid = g.playerid
GROUP BY b.playerid, b.total_achievements, b.games_with_achievements, b.library_size
ORDER BY b.playerid;
```

**Branch D: Review Features**
```sql
SELECT 
    r.playerid,
    COUNT(r.review_id) AS total_reviews,
    AVG(LENGTH(r.review_text)) AS avg_review_length,
    MIN(LENGTH(r.review_text)) AS min_review_length,
    COUNT(*) FILTER (WHERE l.playtime_mins = 0)::NUMERIC / NULLIF(COUNT(r.review_id), 0) AS review_unplayed_ratio,
    1.0 - (COUNT(DISTINCT LOWER(TRIM(r.review_text)))::NUMERIC / NULLIF(COUNT(r.review_id), 0)) AS review_duplication_rate
FROM dw.fact_review r
LEFT JOIN dw.fact_library l ON r.playerid = l.playerid AND r.appid = l.appid
GROUP BY r.playerid
ORDER BY r.playerid;
```

**Branch E: Account Age Features**
```sql
SELECT 
    p.playerid,
    EXTRACT(DAY FROM (MIN(u.date_acquired) - p.date_created)) AS days_before_first_achievement,
    EXTRACT(DAY FROM (NOW() - p.date_created)) AS account_age_days
FROM dw.dim_player p
LEFT JOIN dw.fact_achievement_unlock u ON p.playerid = u.playerid
GROUP BY p.playerid, p.date_created
ORDER BY p.playerid;
```

**Branch F: Playtime Features**
```sql
WITH unique_playtime AS (
    SELECT playerid, appid, MAX(playtime_mins) as playtime_mins
    FROM dw.fact_library
    GROUP BY playerid, appid
)
SELECT 
    u.playerid,
    COUNT(u.appid) FILTER (WHERE l.playtime_mins = 0)::NUMERIC / NULLIF(COUNT(u.appid), 0) AS zero_playtime_achievements_ratio,
    SUM(l.playtime_mins) AS total_playtime_mins,
    SUM(l.playtime_mins)::NUMERIC / NULLIF(COUNT(u.appid), 0) AS playtime_per_achievement
FROM dw.fact_achievement_unlock u
LEFT JOIN unique_playtime l ON u.playerid = l.playerid AND u.appid = l.appid
GROUP BY u.playerid
ORDER BY u.playerid;
```

**Final Pentaho Orchestration Instruction:**
1. Append a **Sort Rows** step (ascending by `playerid`) to the output of every Table Input.
2. Link the outputs together using a cascading chain of **Merge Join** steps configured for `INNER JOIN` on the `playerid` key.
3. Terminate the fully merged stream into a **Table Output** node pointing to `dm.dm_steam_player_features_v1`.
```