import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

STEAM_PLAYER_SUMMARIES_URL = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
STEAM_OWNED_GAMES_URL = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"

logger = logging.getLogger("steam_crawler")

def _setup_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def _truncate(text: str, max_len: int = 250) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

def _sleep_seconds_from_env(var_name: str, default: float) -> float:
    raw = os.getenv(var_name)
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default

def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")

def _unix_to_datetime_string(unix_ts: Optional[int]) -> Optional[str]:
    if not unix_ts:
        return None
    return datetime.fromtimestamp(int(unix_ts)).strftime("%Y-%m-%d %H:%M:%S")

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _read_playerids_from_file(path: Path) -> List[str]:
    playerids: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        playerids.append(raw)
    return playerids

def _read_playerids_from_env() -> List[str]:
    raw = os.getenv("MANUAL_PLAYERIDS")
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[\s,]+", raw) if p.strip()]
    return parts

def _chunked(items: Sequence[str], chunk_size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), chunk_size):
        yield list(items[i : i + chunk_size])

@dataclass(frozen=True)
class CrawlOutputs:
    players_rows: List[Dict[str, Any]]
    purchased_games_rows: List[Dict[str, Any]]
    private_playerids: List[str]

class SteamApiClient:
    def __init__(self, api_key: str, timeout_sec: int = 30):
        self._api_key = api_key
        self._timeout = timeout_sec
        self._session = requests.Session()

    def _get_json(
        self,
        url: str,
        params: Dict[str, Any],
        *,
        max_retries: int = 5,
        log_context: str = "",
    ) -> Optional[Dict[str, Any]]:
        params = dict(params)
        params["key"] = self._api_key

        backoff_sec = 1.0
        for attempt in range(max_retries):
            start = time.perf_counter()
            try:
                r = self._session.get(url, params=params, timeout=self._timeout)
                elapsed_ms = (time.perf_counter() - start) * 1000

                if r.status_code in (400, 401, 403, 404):
                    body_snippet = ""
                    try:
                        body_snippet = _truncate(r.text or "")
                    except Exception:
                        pass
                    logger.warning(
                        "HTTP %s on %s %s (%.0fms) body=%s",
                        r.status_code,
                        url,
                        log_context,
                        elapsed_ms,
                        body_snippet,
                    )
                    return None

                if r.status_code == 429 or 500 <= r.status_code < 600:
                    logger.warning(
                        "Transient HTTP %s on %s %s (attempt %s/%s); backing off %.1fs",
                        r.status_code,
                        url,
                        log_context,
                        attempt + 1,
                        max_retries,
                        backoff_sec,
                    )
                    time.sleep(backoff_sec)
                    backoff_sec = min(backoff_sec * 2, 10)
                    continue

                r.raise_for_status()
                logger.debug("HTTP 200 on %s %s (%.0fms)", url, log_context, elapsed_ms)
                return r.json()
            except Exception as e:
                if attempt == max_retries - 1:
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    logger.warning("Request failed for %s %s (%.0fms): %s", url, log_context, elapsed_ms, str(e))
                    return None
                time.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2, 10)
        return None

    def get_player_summaries(self, playerids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        summaries: Dict[str, Dict[str, Any]] = {}
        for chunk in _chunked(list(playerids), 100):
            data = self._get_json(
                STEAM_PLAYER_SUMMARIES_URL,
                {"steamids": ",".join(chunk)},
                log_context=f"steamids={len(chunk)}",
            )
            players = (data or {}).get("response", {}).get("players", [])
            for p in players:
                steamid = str(p.get("steamid"))
                summaries[steamid] = p
        return summaries

    def get_owned_games(self, playerid: str) -> Optional[List[Dict[str, Any]]]:
        data = self._get_json(
            STEAM_OWNED_GAMES_URL,
            {
                "steamid": playerid,
                "include_appinfo": 0,
                "include_played_free_games": 1,
            },
            log_context=f"steamid={playerid}",
        )
        games = (data or {}).get("response", {}).get("games")
        if not games:
            return None
        return list(games)

def crawl_all(playerids: Sequence[str], api_key: str) -> CrawlOutputs:
    api = SteamApiClient(api_key=api_key)
    playerids = [str(p) for p in playerids]
    summaries = api.get_player_summaries(playerids)

    players_rows: List[Dict[str, Any]] = []
    purchased_games_rows: List[Dict[str, Any]] = []
    private_playerids: List[str] = []

    logger.info("Crawling %s playerids for playtime update", len(playerids))

    for player_index, playerid in enumerate(playerids, start=1):
        p = summaries.get(playerid)
        if not p:
            private_playerids.append(playerid)
            logger.info("Player %s: missing from summaries (private/invalid)", playerid)
            continue

        players_rows.append(
            {
                "playerid": playerid,
                "country": p.get("loccountrycode") or "",
                "created": _unix_to_datetime_string(p.get("timecreated")) or "",
            }
        )

        games = api.get_owned_games(playerid)
        if games is None:
            private_playerids.append(playerid)
            logger.info("Player %s: owned games unavailable (private/invalid)", playerid)
            continue

        library_json = json.dumps(
            [{"appid": g["appid"], "playtime_mins": g.get("playtime_forever", 0)} for g in games if "appid" in g],
            separators=(",", ":")
        )
        purchased_games_rows.append({"playerid": playerid, "library": library_json})

        if player_index % 10 == 0:
            logger.info("Processed %s/%s players", player_index, len(playerids))

    return CrawlOutputs(
        players_rows=players_rows,
        purchased_games_rows=purchased_games_rows,
        private_playerids=sorted(set(private_playerids)),
    )

def _write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

def _write_manifest(output_dir: Path, extract_dt: str, files: List[Path]) -> None:
    manifest: Dict[str, Any] = {
        "schema_version": "steam_extract_v1",
        "extract_dt": extract_dt,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": {},
    }

    for file_path in files:
        rows = 0
        columns: List[str] = []
        with file_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                columns = next(reader)
            except StopIteration:
                columns = []
            for _ in reader:
                rows += 1

        manifest["files"][file_path.name] = {
            "rows": rows,
            "columns": columns,
            "sha256": _sha256_file(file_path),
        }

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Steam crawler (Playtime update only)"
    )
    parser.add_argument("--playerids", nargs="+", help="One or more Steam64 player IDs.")
    parser.add_argument("--playerids-file", type=str, help="Path to a text file with one Steam64 ID per line.")
    parser.add_argument("--output-root", type=str, default="Datasets/landing", help="Root folder for landing drops.")
    parser.add_argument("--extract-dt", type=str, default=None, help="Partition name suffix.")
    parser.add_argument("--api-key", type=str, default=None, help="Steam Web API key.")
    return parser.parse_args(argv)

def main(argv: Optional[Sequence[str]] = None) -> int:
    _setup_logging()
    load_dotenv(override=False)
    args = parse_args(argv)

    api_key = args.api_key or os.getenv("STEAM_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        logger.error("Missing Steam API key.")
        return 2

    playerids: List[str] = []
    if args.playerids_file:
        playerids.extend(_read_playerids_from_file(Path(args.playerids_file)))
    if args.playerids:
        playerids.extend([str(x) for x in args.playerids])
    if not playerids:
        playerids.extend(_read_playerids_from_env())
    playerids = [p.strip() for p in playerids if p.strip()]
    if not playerids:
        logger.error("No player IDs provided. Use --playerids, --playerids-file, or set MANUAL_PLAYERIDS in .env.")
        return 2
    playerids = sorted(set(playerids))

    extract_dt = args.extract_dt or _utc_now_compact()
    output_root = Path(args.output_root)
    output_dir = output_root / f"extract_dt={extract_dt}"
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = crawl_all(playerids, api_key)

    players_csv = output_dir / "players.csv"
    purchased_games_csv = output_dir / "purchased_games.csv"
    history_csv = output_dir / "history.csv"
    reviews_csv = output_dir / "reviews.csv"
    private_csv = output_dir / "private_steamids.csv"

    _write_csv(players_csv, ["playerid", "country", "created"], outputs.players_rows)
    _write_csv(purchased_games_csv, ["playerid", "library"], outputs.purchased_games_rows)
    
    # Write empty files for the others so output structure remains identical
    _write_csv(history_csv, ["playerid", "achievementid", "date_acquired"], [])
    _write_csv(reviews_csv, ["reviewid", "playerid", "gameid", "review", "helpful", "funny", "awards", "posted"], [])
    _write_csv(private_csv, ["playerid"], [{"playerid": p} for p in outputs.private_playerids])

    _write_manifest(output_dir, extract_dt, [players_csv, purchased_games_csv, history_csv, reviews_csv, private_csv])
    (output_dir / "_SUCCESS").write_text("", encoding="utf-8")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
