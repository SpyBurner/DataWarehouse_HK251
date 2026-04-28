-- Postgres bootstrap (idempotent)
-- Initializes the Warehouse DB with DW + Datamart schemas/tables.

-- DW schema
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.dim_player (
    playerid        VARCHAR(30) PRIMARY KEY,
    country         VARCHAR(50),
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

CREATE TABLE IF NOT EXISTS dw.stg_library_temp (
    playerid    VARCHAR(30) NOT NULL,
    library     TEXT
);

CREATE TABLE IF NOT EXISTS dw.dim_game (
    gameid              VARCHAR(30) PRIMARY KEY,
    title               VARCHAR(255),
    release_date        DATE
);

CREATE TABLE IF NOT EXISTS dw.dim_achievement (
    achievementid   VARCHAR(200) PRIMARY KEY,
    gameid          VARCHAR(30),
    title           VARCHAR(255),
    description     TEXT
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

ALTER TABLE dw.dim_achievement
    ADD CONSTRAINT fk_dim_achieve_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

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

-- -----------------------------------------------------------------------------
-- Default Data Initialization (-1 values for Referential Integrity Fallbacks)
-- -----------------------------------------------------------------------------
INSERT INTO dw.dim_player (playerid, country, created, is_private) VALUES ('-1', 'Unknown', '1970-01-01', false) ON CONFLICT (playerid) DO NOTHING;
INSERT INTO dw.dim_game (gameid, title, release_date) VALUES ('-1', 'Unknown', '1970-01-01') ON CONFLICT (gameid) DO NOTHING;
INSERT INTO dw.dim_achievement (achievementid, gameid, title, description) VALUES ('-1', '-1', 'Unknown', 'Unknown') ON CONFLICT (achievementid) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Transformation Handling via Database Triggers
-- -----------------------------------------------------------------------------
-- Bypasses Pentaho row-level Error Hop degradation by actively intercepting 
-- inserts/updates and routing missing FK associations to our '-1' dummy records.

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_review() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN NEW.playerid := '-1'; END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.gameid) THEN NEW.gameid := '-1'; END IF;

    IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM dw.fact_review WHERE reviewid = NEW.reviewid AND playerid = NEW.playerid) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_review_fk BEFORE INSERT OR UPDATE ON dw.fact_review FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_review();

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_dim_achievement() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.gameid) THEN NEW.gameid := '-1'; END IF;

    IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM dw.dim_achievement WHERE achievementid = NEW.achievementid) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_achieve_dim_fk BEFORE INSERT OR UPDATE ON dw.dim_achievement FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_dim_achievement();

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_achievement() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN NEW.playerid := '-1'; END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.dim_achievement WHERE achievementid = NEW.achievementid) THEN NEW.achievementid := '-1'; END IF;

    IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM dw.fact_achievement_unlock WHERE playerid = NEW.playerid AND achievementid = NEW.achievementid) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_achieve_fk BEFORE INSERT OR UPDATE ON dw.fact_achievement_unlock FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_achievement();

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_library() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN NEW.playerid := '-1'; END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.appid) THEN NEW.appid := '-1'; END IF;

    IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM dw.fact_library WHERE playerid = NEW.playerid AND appid = NEW.appid) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_library_fk BEFORE INSERT OR UPDATE ON dw.fact_library FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_library();
