USE master;
GO

-- Create the fresh database
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'DW_Staging')
CREATE DATABASE DW_Staging;
GO