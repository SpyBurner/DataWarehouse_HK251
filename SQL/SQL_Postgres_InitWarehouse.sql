-- Postgres bootstrap (idempotent)
-- Initializes the Warehouse DB with DW + Datamart schemas/tables.

-- DW schema
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.dim_player (
    playerid        VARCHAR(30) PRIMARY KEY,
    country         VARCHAR(10),
    created         TIMESTAMP,
    is_private      BOOLEAN,
    updated_at      TIMESTAMP DEFAULT NOW()
);
 
CREATE TABLE IF NOT EXISTS dw.fact_achievement_unlock (
    playerid        VARCHAR(30) NOT NULL,
    achievementid   VARCHAR(200) NOT NULL,
    date_acquired   TIMESTAMP,
    PRIMARY KEY (playerid, achievementid)
);

CREATE TABLE IF NOT EXISTS dw.fact_review (
    reviewid    VARCHAR(30) NOT NULL,
    playerid    VARCHAR(30) NOT NULL,
    gameid      VARCHAR(30) NOT NULL,
    review      TEXT,
    helpful     INTEGER DEFAULT 0,
    funny       INTEGER DEFAULT 0,
    awards      INTEGER DEFAULT 0,
    posted      DATE, -- Added missing comma here
    PRIMARY KEY (reviewid, playerid)
);

CREATE TABLE IF NOT EXISTS dw.fact_library (
    playerid    VARCHAR(30) NOT NULL,
    appid       VARCHAR(30) NOT NULL,
    PRIMARY KEY (playerid, appid)
);

CREATE TABLE IF NOT EXISTS dw.dim_game (
    gameid              VARCHAR(30) PRIMARY KEY,
    title               VARCHAR(255),
    release_date        DATE
);

CREATE TABLE IF NOT EXISTS dw.dim_developer (
    developerid SERIAL PRIMARY KEY,
    name         VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.bridge_game_developer (
    gameid      VARCHAR(30) NOT NULL,
    developerid INTEGER NOT NULL,
    PRIMARY KEY (gameid, developerid)
);

CREATE TABLE IF NOT EXISTS dw.dim_publisher (
    publisherid SERIAL PRIMARY KEY,
    name         VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.bridge_game_publisher (
    gameid       VARCHAR(30) NOT NULL,
    publisherid INTEGER NOT NULL,
    PRIMARY KEY (gameid, publisherid)
);

CREATE TABLE IF NOT EXISTS dw.dim_genre (
    genreid SERIAL PRIMARY KEY,
    name     VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.bridge_game_genre (
    gameid   VARCHAR(30) NOT NULL,
    genreid INTEGER NOT NULL,
    PRIMARY KEY (gameid, genreid)
);

CREATE TABLE IF NOT EXISTS dw.dim_language (
    languageid SERIAL PRIMARY KEY,
    name        VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.bridge_game_language (
    gameid      VARCHAR(30) NOT NULL,
    languageid INTEGER NOT NULL,
    PRIMARY KEY (gameid, languageid)
);

CREATE TABLE IF NOT EXISTS dw.dim_achievement (
    achievementid   VARCHAR(200) PRIMARY KEY,
    gameid          VARCHAR(30),
    title           VARCHAR(255),
    description     TEXT
);

CREATE TABLE IF NOT EXISTS dw.dim_price (
    gameid          VARCHAR(30) PRIMARY KEY,
    usd             NUMERIC(10, 2),
    eur             NUMERIC(10, 2),
    gbp             NUMERIC(10, 2),
    jpy             NUMERIC(10, 2),
    rub             NUMERIC(10, 2),
    date_acquired   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dw.bridge_friend (
    playerid    VARCHAR(30) NOT NULL,
    friend_playerid VARCHAR(30) NOT NULL,
    PRIMARY KEY (playerid, friend_playerid)
);

-- Enforce relationships for facts
ALTER TABLE dw.fact_review 
    ADD CONSTRAINT fk_review_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_review_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

ALTER TABLE dw.fact_achievement_unlock 
    ADD CONSTRAINT fk_achieve_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_achieve_dim FOREIGN KEY (achievementid) REFERENCES dw.dim_achievement(achievementid);

ALTER TABLE dw.fact_library 
    ADD CONSTRAINT fk_library_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_library_game FOREIGN KEY (appid) REFERENCES dw.dim_game(gameid);

-- Enforce relationships for bridges and dimensions
ALTER TABLE dw.bridge_game_developer
    ADD CONSTRAINT fk_bridge_gd_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid),
    ADD CONSTRAINT fk_bridge_gd_dev FOREIGN KEY (developerid) REFERENCES dw.dim_developer(developerid);

ALTER TABLE dw.bridge_game_publisher
    ADD CONSTRAINT fk_bridge_gp_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid),
    ADD CONSTRAINT fk_bridge_gp_pub FOREIGN KEY (publisherid) REFERENCES dw.dim_publisher(publisherid);

ALTER TABLE dw.bridge_game_genre
    ADD CONSTRAINT fk_bridge_gg_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid),
    ADD CONSTRAINT fk_bridge_gg_genre FOREIGN KEY (genreid) REFERENCES dw.dim_genre(genreid);

ALTER TABLE dw.bridge_game_language
    ADD CONSTRAINT fk_bridge_gl_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid),
    ADD CONSTRAINT fk_bridge_gl_lang FOREIGN KEY (languageid) REFERENCES dw.dim_language(languageid);

ALTER TABLE dw.bridge_friend
    ADD CONSTRAINT fk_bf_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_bf_friend FOREIGN KEY (friend_playerid) REFERENCES dw.dim_player(playerid);

ALTER TABLE dw.dim_achievement
    ADD CONSTRAINT fk_dim_achieve_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

ALTER TABLE dw.dim_price
    ADD CONSTRAINT fk_dim_price_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

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
    refreshid   SERIAL PRIMARY KEY,
    refreshed_at TIMESTAMP DEFAULT NOW(),
    player_count INTEGER,
    status       VARCHAR(20)
);
