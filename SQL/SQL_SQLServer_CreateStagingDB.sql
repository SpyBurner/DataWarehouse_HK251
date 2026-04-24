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
		extract_dt       NVARCHAR(50)   NOT NULL,
		loaded_at        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
		status           NVARCHAR(20)   NOT NULL,
		players_rows     INT,
		history_rows     INT,
		reviews_rows     INT,
		library_rows     INT,
		private_rows     INT,
		error_message    NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.stg_players', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_players (
		playerid     NVARCHAR(30)  NOT NULL,
		country      NVARCHAR(10),
		created      NVARCHAR(30),
		extract_dt   NVARCHAR(50)  NOT NULL,
		loaded_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_history', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_history (
		playerid        NVARCHAR(30)  NOT NULL,
		achievementid   NVARCHAR(200) NOT NULL,
		date_acquired   NVARCHAR(30),
		extract_dt      NVARCHAR(50)  NOT NULL,
		loaded_at       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_reviews', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_reviews (
		reviewid    NVARCHAR(30)  NOT NULL,
		playerid    NVARCHAR(30)  NOT NULL,
		gameid      NVARCHAR(30),
		review      NVARCHAR(MAX),
		helpful     INT,
		funny       INT,
		awards      INT,
		posted      NVARCHAR(30),
		extract_dt  NVARCHAR(50)  NOT NULL,
		loaded_at   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_library', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_library (
		playerid            NVARCHAR(30)  NOT NULL,
		library_list_string NVARCHAR(MAX),
		extract_dt          NVARCHAR(50)  NOT NULL,
		loaded_at           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

IF OBJECT_ID('dbo.stg_private_steamids', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.stg_private_steamids (
		playerid    NVARCHAR(30) NOT NULL,
		extract_dt  NVARCHAR(50) NOT NULL,
		loaded_at   DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME()
	);
END;

/* ------------------------------
   Raw mirror tables (raw_*)
   ------------------------------ */
IF OBJECT_ID('dbo.raw_achievements', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_achievements (
		[achievementid] NVARCHAR(MAX),
		[gameid]        NVARCHAR(MAX),
		[title]         NVARCHAR(MAX),
		[description]   NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_friends', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_friends (
		[playerid] NVARCHAR(MAX),
		[friends]  NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_games', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_games (
		[gameid]              NVARCHAR(MAX),
		[title]               NVARCHAR(MAX),
		[developers]          NVARCHAR(MAX),
		[publishers]          NVARCHAR(MAX),
		[genres]              NVARCHAR(MAX),
		[supported_languages] NVARCHAR(MAX),
		[release_date]        NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_history', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_history (
		[playerid]      NVARCHAR(MAX),
		[achievementid] NVARCHAR(MAX),
		[date_acquired] NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_players', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_players (
		[playerid] NVARCHAR(MAX),
		[country]  NVARCHAR(MAX),
		[created]  NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_prices', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_prices (
		[gameid]        NVARCHAR(MAX),
		[usd]           NVARCHAR(MAX),
		[eur]           NVARCHAR(MAX),
		[gbp]           NVARCHAR(MAX),
		[jpy]           NVARCHAR(MAX),
		[rub]           NVARCHAR(MAX),
		[date_acquired] NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_private_steamids', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_private_steamids (
		[playerid] NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_purchased_games', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_purchased_games (
		[playerid] NVARCHAR(MAX),
		[library]  NVARCHAR(MAX)
	);
END;

IF OBJECT_ID('dbo.raw_reviews', 'U') IS NULL
BEGIN
	CREATE TABLE dbo.raw_reviews (
		[reviewid] NVARCHAR(MAX),
		[playerid] NVARCHAR(MAX),
		[gameid]   NVARCHAR(MAX),
		[review]   NVARCHAR(MAX),
		[helpful]  NVARCHAR(MAX),
		[funny]    NVARCHAR(MAX),
		[awards]   NVARCHAR(MAX),
		[posted]   NVARCHAR(MAX)
	);
END;

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
