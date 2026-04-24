-- Postgres bootstrap (idempotent)
-- Initializes the Warehouse DB with DW + Datamart schemas/tables.

-- DW schema
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.dim_player (
    playerid        VARCHAR(30) PRIMARY KEY,
    country         VARCHAR(10),
    created         TIMESTAMP,
    first_seen_dt   VARCHAR(50),
    last_seen_dt    VARCHAR(50),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dw.fact_achievement_unlock (
    playerid        VARCHAR(30) NOT NULL,
    achievementid   VARCHAR(200) NOT NULL,
    gameid          VARCHAR(30),
    date_acquired   TIMESTAMP,
    extract_dt      VARCHAR(50) NOT NULL,
    PRIMARY KEY (playerid, achievementid)
);

CREATE TABLE IF NOT EXISTS dw.fact_review (
    reviewid    VARCHAR(30) PRIMARY KEY,
    playerid    VARCHAR(30) NOT NULL,
    gameid      VARCHAR(30),
    review      TEXT,
    helpful     INTEGER DEFAULT 0,
    funny       INTEGER DEFAULT 0,
    awards      INTEGER DEFAULT 0,
    posted      DATE,
    extract_dt  VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.fact_library (
    playerid    VARCHAR(30) NOT NULL,
    appid       VARCHAR(30) NOT NULL,
    extract_dt  VARCHAR(50) NOT NULL,
    PRIMARY KEY (playerid, appid)
);

-- Datamart schema
CREATE SCHEMA IF NOT EXISTS dm;

CREATE TABLE IF NOT EXISTS dm.dm_steam_player_features_v1 (
    playerid                        VARCHAR(30) PRIMARY KEY,
    country                         VARCHAR(10),
    account_age_days                DOUBLE PRECISION,
    library_size                    INTEGER,
    total_achievements              INTEGER,
    achievement_game_ratio          DOUBLE PRECISION,
    total_reviews                   INTEGER,
    avg_review_length               DOUBLE PRECISION,
    min_review_length               DOUBLE PRECISION,
    review_duplication_rate         DOUBLE PRECISION,
    refreshed_at                    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dm.dm_datamart_refresh_log (
    refresh_id   SERIAL PRIMARY KEY,
    refreshed_at TIMESTAMP DEFAULT NOW(),
    player_count INTEGER,
    status       VARCHAR(20)
);
