from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

DB_HOST = os.getenv("ML_ANALYTICS_DB_HOST_DOCKER", os.getenv("ML_ANALYTICS_DB_HOST", "localhost"))
DB_PORT = int(os.getenv("ML_ANALYTICS_DB_PORT", "5432"))
DB_NAME = os.getenv("ML_ANALYTICS_DB_NAME", "Warehouse")
DB_USER = os.getenv("ML_ANALYTICS_DB_USER", "postgres")
DB_PASSWORD = os.getenv("ML_ANALYTICS_DB_PASSWORD", "31082004@Lmao")
DATAMART_FEATURE_TABLE = os.getenv(
    "ML_ANALYTICS_DATAMART_FEATURE_TABLE",
    "dm.dm_steam_player_features_v1",
)
DATAMART_DROP_COLUMNS = [
    col.strip()
    for col in os.getenv("ML_ANALYTICS_DATAMART_DROP_COLUMNS", "country").split(",")
    if col.strip()
]


def _split_qualified_name(qualified_name: str) -> tuple[str, str]:
    if "." in qualified_name:
        schema, table = qualified_name.split(".", 1)
    else:
        schema, table = "public", qualified_name
    return schema, table


def load_datamart_table(table_name: str | None = None) -> pd.DataFrame:
    """Load a datamart table from Postgres using the project environment settings."""
    schema, table = _split_qualified_name(table_name or DATAMART_FEATURE_TABLE)
    query = f'SELECT * FROM "{schema}"."{table}"'

    connection_kwargs = {
        "host": DB_HOST,
        "port": DB_PORT,
        "dbname": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
    }

    with psycopg2.connect(**connection_kwargs) as connection:
        return pd.read_sql_query(query, connection)


def load_feature_matrix_from_datamart() -> pd.DataFrame:
    """Load the modeling feature matrix from the prepared datamart table."""
    frame = load_datamart_table()

    if "playerid" not in frame.columns:
        raise ValueError("Datamart feature table is missing required column: playerid")

    frame = frame.copy()
    frame["playerid"] = pd.to_numeric(frame["playerid"], errors="coerce")
    frame = frame.dropna(subset=["playerid"]).copy()
    frame["playerid"] = frame["playerid"].astype("int64")
    frame = frame.set_index("playerid")

    columns_to_drop = [col for col in DATAMART_DROP_COLUMNS if col in frame.columns]
    if columns_to_drop:
        frame = frame.drop(columns=columns_to_drop)

    return frame