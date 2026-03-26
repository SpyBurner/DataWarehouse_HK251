USE master;
GO

-- Forcefully close any existing connections and drop the database
IF EXISTS (SELECT * FROM sys.databases WHERE name = 'DW_Staging')
BEGIN
    ALTER DATABASE DW_Staging SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE DW_Staging;
END
GO

-- Create the fresh database
CREATE DATABASE DW_Staging;
GO