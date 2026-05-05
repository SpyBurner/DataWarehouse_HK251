"""
Phase 1: Data ETL & Memory Optimization for Steam Anomaly Detection
Reads from Postgres Data Warehouse, cleans data, and exports as .parquet.
"""

import os
import json
import logging
import pandas as pd
from sqlalchemy import create_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed")

# ---------------------------------------------------------------------------
# Database Connection
# ---------------------------------------------------------------------------

def get_engine():
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "31082004@Lmao")
    dbname = os.getenv("DB_NAME", "Warehouse")
    conn_str = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    return create_engine(conn_str)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_list_fast(s: str) -> list:
    """
    Parse a Python-style list string or JSON string into a structured list of dicts.
    Handles both the old format [10, 20, 30] and the new format [{"appid": 10, "playtime_mins": 0}].
    """
    if not isinstance(s, str) or not s.strip():
        return []
    try:
        parsed_data = json.loads(s.replace("'", '"'))
        
        if not parsed_data:
            return []
            
        # Nếu dữ liệu là định dạng cũ (danh sách các số nguyên/chuỗi)
        if isinstance(parsed_data[0], (int, str)):
            return [{"appid": int(appid), "playtime_mins": -1} for appid in parsed_data]
            
        # Nếu dữ liệu là định dạng mới (danh sách các từ điển)
        elif isinstance(parsed_data[0], dict):
            return [{"appid": int(item.get("appid", -1)), "playtime_mins": int(item.get("playtime_mins", -1))} for item in parsed_data if "appid" in item]
            
        return []
    except (ValueError, TypeError):
        return []

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_history(engine) -> pd.DataFrame:
    log.info("Loading history from DW ...")
    query = """
        SELECT h.playerid, h.achievementid, h.date_acquired
        FROM dw.fact_achievement_unlock h
        JOIN dw.dim_player p ON h.playerid = p.playerid
        WHERE p.is_private = FALSE
    """
    df = pd.read_sql(query, engine)
    log.info("  Raw rows: %d", len(df))

    # Extract gameid safely — achievement names may contain underscores
    df["gameid"] = (
        df["achievementid"]
        .str.extract(r"^(\d+)_")[0]
        .astype("Int32")  # nullable int to handle non-matching rows
    )

    # Fast datetime parse with explicit format
    df["date_acquired"] = pd.to_datetime(
        df["date_acquired"], errors="coerce"
    )

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["playerid", "achievementid", "date_acquired"], keep="last").reset_index(drop=True)
    log.info("  Removed %d duplicate rows.", before - len(df))
    log.info("  Final rows: %d", len(df))
    return df

def load_players(engine) -> pd.DataFrame:
    log.info("Loading players from DW ...")
    query = """
        SELECT playerid, country, created
        FROM dw.dim_player
        WHERE is_private = FALSE
    """
    df = pd.read_sql(query, engine)
    log.info("  Raw rows: %d", len(df))

    df["created"] = pd.to_datetime(
        df["created"], errors="coerce"
    )

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["playerid"], keep="last").reset_index(drop=True)
    log.info("  Removed %d duplicate rows.", before - len(df))
    log.info("  Final rows: %d", len(df))
    return df

def load_reviews(engine) -> pd.DataFrame:
    log.info("Loading reviews from DW ...")
    query = """
        SELECT r.reviewid, r.playerid, r.gameid, r.review, r.helpful, r.funny, r.awards, r.posted
        FROM dw.fact_review r
        JOIN dw.dim_player p ON r.playerid = p.playerid
        WHERE p.is_private = FALSE
    """
    df = pd.read_sql(query, engine)
    log.info("  Raw rows: %d", len(df))

    df["posted"] = pd.to_datetime(df["posted"], errors="coerce")

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["reviewid"], keep="last").reset_index(drop=True)
    log.info("  Removed %d duplicate rows.", before - len(df))
    log.info("  Final rows: %d", len(df))
    return df

def load_purchased(engine) -> pd.DataFrame:
    log.info("Loading purchased_games from DW ...")
    query = """
        SELECT l.playerid, json_agg(json_build_object('appid', l.appid, 'playtime_mins', l.playtime_mins))::text AS library
        FROM dw.fact_library l
        JOIN dw.dim_player p ON l.playerid = p.playerid
        WHERE p.is_private = FALSE
        GROUP BY l.playerid
    """
    df = pd.read_sql(query, engine)
    
    # Needs to match old dtype
    df["playerid"] = df["playerid"].astype("int64")
    log.info("  Raw rows: %d", len(df))

    # Fast list parsing instead of ast.literal_eval
    df["library"] = df["library"].apply(_parse_list_fast)
    df["library_size"] = df["library"].apply(len).astype("int32")

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["playerid"], keep="last").reset_index(drop=True)
    log.info("  Removed %d duplicate rows.", before - len(df))
    log.info("  Final rows: %d", len(df))
    return df

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    log.info("Output directory: %s", os.path.abspath(PROCESSED_DIR))

    engine = get_engine()

    datasets = {
        "history":   load_history(engine),
        "players":   load_players(engine),
        "reviews":   load_reviews(engine),
        "purchased": load_purchased(engine),
    }

    for name, df in datasets.items():
        out_path = os.path.join(PROCESSED_DIR, f"{name}.parquet")
        df.to_parquet(out_path, index=False, compression="snappy")
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        log.info("Saved %s.parquet  (%.1f MB,  %d rows)", name, size_mb, len(df))

    log.info("Phase 1 complete.")

if __name__ == "__main__":
    main()
