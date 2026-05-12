-- Postgres bootstrap (idempotent)
-- Initializes the Warehouse DB with DW + Datamart schemas/tables.

-- DW schema
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.dim_country_utc_offset (
    country     VARCHAR(10) PRIMARY KEY,
    utc_offset  INTEGER NOT NULL
);

INSERT INTO dw.dim_country_utc_offset (country, utc_offset) VALUES
    ('US', -5), ('CA', -5), ('MX', -6), ('BR', -3), ('AR', -3), ('CL', -4), ('CO', -5), ('PE', -5),
    ('GB', 0),  ('IE', 0),  ('DE', 1),  ('FR', 1),  ('PL', 1),  ('ES', 1),  ('IT', 1),
    ('NL', 1),  ('BE', 1),  ('AT', 1),  ('CH', 1),  ('CZ', 1),  ('SE', 1),  ('NO', 1),
    ('DK', 1),  ('FI', 2),  ('PT', 0),  ('RO', 2),  ('HU', 1),  ('SK', 1),  ('HR', 1),
    ('RU', 3),  ('UA', 2),  ('BY', 3),  ('TR', 3),  ('IL', 2),  ('EG', 2),  ('SA', 3),  ('AE', 4),
    ('CN', 8),  ('JP', 9),  ('KR', 9),  ('TW', 8),  ('HK', 8),  ('SG', 8),  ('TH', 7),
    ('VN', 7),  ('ID', 7),  ('MY', 8),  ('PH', 8),  ('IN', 5),  ('AU', 10), ('NZ', 12),
    ('ZA', 2),  ('NG', 1),  ('KE', 3)
ON CONFLICT (country) DO UPDATE SET utc_offset = EXCLUDED.utc_offset;

CREATE TABLE IF NOT EXISTS dw.dim_player (
    playerid        VARCHAR(30) PRIMARY KEY,
    country         VARCHAR(50),
    created         TIMESTAMP,
    is_private      BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMP DEFAULT NOW()
);
 
CREATE TABLE IF NOT EXISTS dw.fact_achievement_unlock (
    playerid        VARCHAR(30) NOT NULL,
    achievementid   TEXT NOT NULL,
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
    playerid      VARCHAR(30) NOT NULL,
    appid         VARCHAR(30) NOT NULL,
    playtime_mins INTEGER DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS dw.fact_achievement (
    achievementid   TEXT PRIMARY KEY,
    gameid          VARCHAR(30)
);


-- Enforce relationships for facts
ALTER TABLE dw.fact_review 
    ADD CONSTRAINT fk_review_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_review_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

ALTER TABLE dw.fact_achievement_unlock 
    ADD CONSTRAINT fk_achieve_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_achieve_dim FOREIGN KEY (achievementid) REFERENCES dw.fact_achievement(achievementid);

ALTER TABLE dw.fact_library 
    ADD CONSTRAINT fk_library_player FOREIGN KEY (playerid) REFERENCES dw.dim_player(playerid),
    ADD CONSTRAINT fk_library_game FOREIGN KEY (appid) REFERENCES dw.dim_game(gameid);

ALTER TABLE dw.fact_achievement
    ADD CONSTRAINT fk_dim_achieve_game FOREIGN KEY (gameid) REFERENCES dw.dim_game(gameid);

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
            entropy := entropy - (p * ln(p));
        END IF;
    END LOOP;

    RETURN ROUND(entropy, 4);
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- -----------------------------------------------------------------------------
-- Default Data Initialization (-1 values for Referential Integrity Fallbacks)
-- -----------------------------------------------------------------------------
INSERT INTO dw.dim_player (playerid, country, created, is_private) VALUES ('-1', 'Unknown', '1970-01-01', false) ON CONFLICT (playerid) DO NOTHING;
INSERT INTO dw.dim_game (gameid, title, release_date) VALUES ('-1', 'Unknown', '1970-01-01') ON CONFLICT (gameid) DO NOTHING;
INSERT INTO dw.fact_achievement (achievementid, gameid) VALUES ('-1', '-1') ON CONFLICT (achievementid) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Transformation Handling via Database Triggers
-- -----------------------------------------------------------------------------
-- Goal:
-- - Reject rows with missing PRIMARY KEY fields (NULL PK).
-- - Never rewrite PRIMARY KEY fields to '-1'.
-- - Only apply '-1' fallback to NON-PK foreign key columns.

-- Idempotent trigger install (PostgreSQL does not support CREATE OR REPLACE TRIGGER)
DROP TRIGGER IF EXISTS trg_review_fk ON dw.fact_review;
DROP TRIGGER IF EXISTS trg_achieve_dim_fk ON dw.fact_achievement;
DROP TRIGGER IF EXISTS trg_achieve_fk ON dw.fact_achievement_unlock;
DROP TRIGGER IF EXISTS trg_library_fk ON dw.fact_library;

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_review()
RETURNS TRIGGER AS $$
BEGIN
    -- PK = (reviewid, playerid)
    IF NEW.reviewid IS NULL OR NEW.playerid IS NULL THEN
        RETURN NULL;
    END IF;

    -- playerid is PK+FK -> reject if missing in dimension (do not rewrite PK)
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN
        RETURN NULL;
    END IF;

    -- gameid is non-PK FK -> fallback allowed
    NEW.gameid := COALESCE(NEW.gameid, '-1');
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.gameid) THEN
        NEW.gameid := '-1';
    END IF;

    -- De-dupe inserts by PK
    IF TG_OP = 'INSERT' THEN
        IF EXISTS (
            SELECT 1
            FROM dw.fact_review
            WHERE reviewid = NEW.reviewid
              AND playerid = NEW.playerid
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_review_fk
BEFORE INSERT OR UPDATE ON dw.fact_review
FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_review();

-- -----------------------------------------------------------------------------
-- dw.fact_achievement trigger
-- (IMPORTANT: dw.fact_achievement has NO playerid. Do not reference NEW.playerid here.)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_achievement()
RETURNS TRIGGER AS $$
BEGIN
    -- PK = achievementid
    IF NEW.achievementid IS NULL THEN
        RETURN NULL;
    END IF;

    -- Normalize non-PK
    NEW.gameid := COALESCE(NEW.gameid, '-1');

    -- FK fallback
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.gameid) THEN
        NEW.gameid := '-1';
    END IF;

    -- De-dupe inserts by PK (achievementid)
    IF TG_OP = 'INSERT' THEN
        IF EXISTS (
            SELECT 1
            FROM dw.fact_achievement
            WHERE achievementid = NEW.achievementid
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_achieve_dim_fk
BEFORE INSERT OR UPDATE ON dw.fact_achievement
FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_achievement();

-- -----------------------------------------------------------------------------
-- dw.fact_achievement_unlock trigger
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_achievement_unlock()
RETURNS TRIGGER AS $$
DECLARE
    v_gameid VARCHAR(30);
BEGIN
    -- PK = (playerid, achievementid)
    IF NEW.playerid IS NULL OR NEW.achievementid IS NULL THEN
        RETURN NULL;
    END IF;

    -- playerid is PK+FK -> hard-reject if player not in dimension
    -- (an unlock with no matching player is genuinely corrupt data)
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN
        RETURN NULL;
    END IF;

    -- achievementid is PK+FK -> auto-create stub if missing so no unlock is lost.
    -- The original Python pipeline keeps all rows regardless of whether the
    -- achievement exists in a reference table; dropping here causes feature drift.
    IF NOT EXISTS (SELECT 1 FROM dw.fact_achievement WHERE achievementid = NEW.achievementid) THEN
        -- Derive gameid from achievementid prefix (format: "<gameid>_<name>")
        v_gameid := split_part(NEW.achievementid, '_', 1);
        IF v_gameid IS NULL OR v_gameid = '' THEN
            v_gameid := '-1';
        END IF;
        -- Ensure the parent game stub exists first
        INSERT INTO dw.dim_game (gameid, title, release_date)
        VALUES (v_gameid, 'Unknown (auto-stub)', NULL)
        ON CONFLICT (gameid) DO NOTHING;
        -- Now insert the achievement stub
        INSERT INTO dw.fact_achievement (achievementid, gameid)
        VALUES (NEW.achievementid, v_gameid)
        ON CONFLICT (achievementid) DO NOTHING;
    END IF;

    -- De-dupe inserts by PK
    IF TG_OP = 'INSERT' THEN
        IF EXISTS (
            SELECT 1
            FROM dw.fact_achievement_unlock
            WHERE playerid = NEW.playerid
              AND achievementid = NEW.achievementid
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_achieve_fk
BEFORE INSERT OR UPDATE ON dw.fact_achievement_unlock
FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_achievement_unlock();

CREATE OR REPLACE FUNCTION dw.trg_fk_fallback_fact_library()
RETURNS TRIGGER AS $$
BEGIN
    -- PK = (playerid, appid)
    IF NEW.playerid IS NULL OR NEW.appid IS NULL THEN
        RETURN NULL;
    END IF;

    -- playerid is PK+FK -> hard-reject if player not in dimension
    -- (a library entry with no matching player is genuinely corrupt data)
    IF NOT EXISTS (SELECT 1 FROM dw.dim_player WHERE playerid = NEW.playerid) THEN
        RETURN NULL;
    END IF;

    -- appid is PK+FK -> auto-create stub game if missing so no library entry is lost.
    -- The original Python pipeline keeps all owned games regardless of whether the
    -- game exists in a metadata table; dropping here shrinks library_size and
    -- corrupts downstream features (achievement_game_ratio, playtime features, etc.).
    IF NOT EXISTS (SELECT 1 FROM dw.dim_game WHERE gameid = NEW.appid) THEN
        INSERT INTO dw.dim_game (gameid, title, release_date)
        VALUES (NEW.appid, 'Unknown (auto-stub)', NULL)
        ON CONFLICT (gameid) DO NOTHING;
    END IF;

    NEW.playtime_mins := COALESCE(NEW.playtime_mins, 0);

    -- De-dupe inserts by PK
    IF TG_OP = 'INSERT' THEN
        IF EXISTS (
            SELECT 1
            FROM dw.fact_library
            WHERE playerid = NEW.playerid
              AND appid = NEW.appid
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_library_fk
BEFORE INSERT OR UPDATE ON dw.fact_library
FOR EACH ROW EXECUTE FUNCTION dw.trg_fk_fallback_fact_library();
