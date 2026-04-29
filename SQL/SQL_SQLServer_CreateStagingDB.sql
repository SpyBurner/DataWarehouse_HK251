/*
  SQL Server staging bootstrap (idempotent)

  - Creates the DW_Staging database (if missing)
  - Creates all staging tables used by the Pentaho pipeline guide (stg_*)
	- Creates one raw table per CSV in Datasets/raw (raw_*) using the CSV headers

  Designed to be safe to run multiple times.
*/

USE master;
GO

IF DB_ID('DW_Staging') IS NULL
BEGIN
	EXEC('CREATE DATABASE DW_Staging');
END;
GO

USE DW_Staging;
GO

/* ------------------------------
   Pipeline staging tables (stg_*)
   ------------------------------ */

IF OBJECT_ID('dbo.stg_load_audit', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_load_audit (
		audit_id         INT IDENTITY(1,1) PRIMARY KEY,
		loaded_at        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
		status           NVARCHAR(20)   NOT NULL,
		players_rows     INT,
		history_rows     INT,
		reviews_rows     INT,
		library_rows     INT,
		private_rows     INT,
		error_message    NVARCHAR(MAX),
		extract_dt	     DATETIME2
	);
END;

IF OBJECT_ID('dbo.stg_players', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_players (
		[playerid]     NVARCHAR(MAX),
		[country]      NVARCHAR(MAX),
		[created]      NVARCHAR(MAX),
		loaded_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_history', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_history (
		[playerid]        NVARCHAR(MAX),
		[achievementid]   NVARCHAR(MAX),
		[date_acquired]   NVARCHAR(MAX),
		loaded_at         DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_reviews', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_reviews (
		[reviewid]    NVARCHAR(MAX),
		[playerid]    NVARCHAR(MAX),
		[gameid]      NVARCHAR(MAX),
		[review]      NVARCHAR(MAX),
		[helpful]     NVARCHAR(MAX),
		[funny]       NVARCHAR(MAX),
		[awards]      NVARCHAR(MAX),
		[posted]      NVARCHAR(MAX),
		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_purchased_games', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_purchased_games (
		[playerid]      NVARCHAR(MAX),
		[library]       NVARCHAR(MAX),
		loaded_at       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_private_steamids', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_private_steamids (
		[playerid]    NVARCHAR(MAX),
		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_achievements', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_achievements (
		[achievementid] NVARCHAR(MAX),
		[gameid]        NVARCHAR(MAX),
		[title]         NVARCHAR(MAX),
		[description]   NVARCHAR(MAX),
		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

-- IF OBJECT_ID('dbo.stg_friends', 'U') IS NULL
-- BEGIN
-- 	CREATE TABLE dbo.stg_friends (
-- 		[playerid] NVARCHAR(MAX),
-- 		[friends]  NVARCHAR(MAX),
-- 		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
-- 	);
-- END;

IF OBJECT_ID('dbo.stg_games', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_games (
		[gameid]              NVARCHAR(MAX),
		[title]               NVARCHAR(MAX),
		[developers]          NVARCHAR(MAX),
		[publishers]          NVARCHAR(MAX),
		[genres]              NVARCHAR(MAX),
		[supported_languages] NVARCHAR(MAX),
		[release_date]        NVARCHAR(MAX),
		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

-- IF OBJECT_ID('dbo.stg_prices', 'U') IS NULL
-- BEGIN
-- 	CREATE TABLE dbo.stg_prices (
-- 		[gameid]        NVARCHAR(MAX),
-- 		[usd]           NVARCHAR(MAX),
-- 		[eur]           NVARCHAR(MAX),
-- 		[gbp]           NVARCHAR(MAX),
-- 		[jpy]           NVARCHAR(MAX),
-- 		[rub]           NVARCHAR(MAX),
-- 		[date_acquired] NVARCHAR(MAX),
-- 		loaded_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
-- 	);
-- END;

/* ------------------------------
   One-time init marker
   ------------------------------ */

IF OBJECT_ID('dbo.__init_marker', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.__init_marker (
		initialized_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
	);
	INSERT INTO dbo.__init_marker DEFAULT VALUES;
END;


-- Job log table
--

CREATE TABLE dbo.pentaho_logging
(
  ID_JOB INT
, CHANNEL_ID VARCHAR(255)
, JOBNAME VARCHAR(255)
, STATUS VARCHAR(15)
, LINES_READ BIGINT
, LINES_WRITTEN BIGINT
, LINES_UPDATED BIGINT
, LINES_INPUT BIGINT
, LINES_OUTPUT BIGINT
, LINES_REJECTED BIGINT
, ERRORS BIGINT
, STARTDATE DATETIME
, ENDDATE DATETIME
, LOGDATE DATETIME
, DEPDATE DATETIME
, REPLAYDATE DATETIME
, LOG_FIELD TEXT
)
;
CREATE INDEX IDX_pentaho_logging_1 ON dbo.pentaho_logging(ID_JOB)
;
CREATE INDEX IDX_pentaho_logging_2 ON dbo.pentaho_logging(ERRORS, STATUS, JOBNAME)
;
CREATE INDEX IDX_pentaho_logging_3 ON dbo.pentaho_logging(JOBNAME, LOGDATE)
;
