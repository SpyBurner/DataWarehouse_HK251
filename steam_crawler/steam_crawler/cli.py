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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


STEAM_PLAYER_SUMMARIES_URL = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
STEAM_OWNED_GAMES_URL = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
STEAM_PLAYER_ACHIEVEMENTS_URL = "http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"


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


def _parse_steam_posted_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        date_str = date_str.strip()
        if "," in date_str:
            dt = datetime.strptime(date_str, "%d %B, %Y")
        else:
            dt = datetime.strptime(f"{date_str} {datetime.now().year}", "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


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

                # For non-retryable client errors, log details and stop.
                if r.status_code in (400, 401, 403, 404):
                    body_snippet = ""
                    try:
                        body_snippet = _truncate(r.text or "")
                    except Exception:
                        body_snippet = ""
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

    def get_player_achievements(self, playerid: str, appid: int) -> Optional[List[Dict[str, Any]]]:
        data = self._get_json(
            STEAM_PLAYER_ACHIEVEMENTS_URL,
            {
                "steamid": playerid,
                "appid": appid,
                # Steam sometimes varies fields by language; keep deterministic.
                "l": "english",
            },
            log_context=f"steamid={playerid} appid={appid}",
        )
        stats = (data or {}).get("playerstats")
        if not stats or not stats.get("success"):
            return None
        achievements = stats.get("achievements")
        if not achievements:
            return None
        return list(achievements)


class SteamCommunityScraper:
    def __init__(self, timeout_sec: int = 30):
        self._timeout = timeout_sec
        self._session = requests.Session()
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def scrape_reviews(self, playerid: str) -> List[Dict[str, Any]]:
        reviews: List[Dict[str, Any]] = []
        page = 1
        while True:
            url = f"https://steamcommunity.com/profiles/{playerid}/recommended/?p={page}&l=english"
            try:
                r = self._session.get(url, headers=self._headers, timeout=self._timeout)
                if r.status_code != 200:
                    logger.info("Reviews: steamid=%s page=%s status=%s; stopping", playerid, page, r.status_code)
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                boxes = soup.find_all("div", class_="review_box")
                if not boxes:
                    logger.info("Reviews: steamid=%s page=%s empty; stopping", playerid, page)
                    break
                for box in boxes:
                    left_link = box.select_one("div.leftcol a")
                    gameid = "0"
                    if left_link and left_link.has_attr("href"):
                        m = re.search(r"/app/(\d+)", left_link["href"])
                        if m:
                            gameid = m.group(1)

                    content_div = box.find("div", class_="content")
                    review_text = content_div.get_text(separator=" ", strip=True) if content_div else ""

                    posted_div = box.find("div", class_="posted")
                    posted_text = posted_div.get_text(strip=True) if posted_div else ""
                    posted_match = re.search(r"Posted (.*?)\.", posted_text)
                    posted = _parse_steam_posted_date(posted_match.group(1)) if posted_match else None

                    vote_btn = box.find("a", id=re.compile(r"RecommendationVoteUpBtn\d+"))
                    reviewid = "0"
                    if vote_btn and vote_btn.has_attr("id"):
                        reviewid = vote_btn["id"].replace("RecommendationVoteUpBtn", "")

                    header_div = box.find("div", class_="header")
                    header_text = header_div.get_text(strip=True) if header_div else ""
                    helpful_match = re.search(
                        r"([\d,]+) (person|people) found this review helpful", header_text
                    )
                    helpful = int(helpful_match.group(1).replace(",", "")) if helpful_match else 0
                    funny_match = re.search(r"([\d,]+) (person|people) found this review funny", header_text)
                    funny = int(funny_match.group(1).replace(",", "")) if funny_match else 0

                    reviews.append(
                        {
                            "reviewid": reviewid,
                            "playerid": str(playerid),
                            "gameid": gameid,
                            "review": review_text,
                            "helpful": helpful,
                            "funny": funny,
                            "awards": 0,
                            "posted": posted,
                        }
                    )

                page += 1
                logger.info("Reviews: steamid=%s scraped page=%s (boxes=%s)", playerid, page - 1, len(boxes))
                time.sleep(0.5)
            except Exception as e:
                logger.warning("Reviews: steamid=%s page=%s error=%s; stopping", playerid, page, str(e))
                break
        return reviews


def crawl_all(playerids: Sequence[str], api_key: str, output_dir: Path) -> None:
    api = SteamApiClient(api_key=api_key)
    scraper = SteamCommunityScraper()

    playerids = [str(p) for p in playerids]
    summaries = api.get_player_summaries(playerids)

    logger.info("Crawling %s playerids", len(playerids))

    achievements_sleep_sec = _sleep_seconds_from_env("STEAM_ACHIEVEMENTS_SLEEP_SEC", 0.2)
    reviews_sleep_sec = _sleep_seconds_from_env("STEAM_REVIEWS_SLEEP_SEC", 0.5)

    logger.info(
        "Rate limits: achievements_sleep_sec=%.3f reviews_sleep_sec=%.3f",
        achievements_sleep_sec,
        reviews_sleep_sec,
    )

    players_csv = output_dir / "players.csv"
    purchased_games_csv = output_dir / "purchased_games.csv"
    history_csv = output_dir / "history.csv"
    reviews_csv = output_dir / "reviews.csv"
    private_csv = output_dir / "private_steamids.csv"

    with open(players_csv, "w", newline="", encoding="utf-8") as f_players, \
         open(purchased_games_csv, "w", newline="", encoding="utf-8") as f_purchased, \
         open(history_csv, "w", newline="", encoding="utf-8") as f_history, \
         open(reviews_csv, "w", newline="", encoding="utf-8") as f_reviews, \
         open(private_csv, "w", newline="", encoding="utf-8") as f_private:

        players_writer = csv.DictWriter(f_players, fieldnames=["playerid", "country", "created"], quoting=csv.QUOTE_NONNUMERIC)
        players_writer.writeheader()

        purchased_writer = csv.DictWriter(f_purchased, fieldnames=["playerid", "library"], quoting=csv.QUOTE_NONNUMERIC)
        purchased_writer.writeheader()

        history_writer = csv.DictWriter(f_history, fieldnames=["playerid", "achievementid", "date_acquired"], quoting=csv.QUOTE_NONNUMERIC)
        history_writer.writeheader()

        reviews_writer = csv.DictWriter(f_reviews, fieldnames=["reviewid", "playerid", "gameid", "review", "helpful", "funny", "awards", "posted"], quoting=csv.QUOTE_NONNUMERIC)
        reviews_writer.writeheader()

        private_writer = csv.DictWriter(f_private, fieldnames=["playerid"], quoting=csv.QUOTE_NONNUMERIC)
        private_writer.writeheader()

        for player_index, playerid in enumerate(playerids, start=1):
            logger.info("Player %s/%s steamid=%s: start", player_index, len(playerids), playerid)
            p = summaries.get(playerid)
            if not p or p.get("communityvisibilitystate") != 3:
                private_writer.writerow({"playerid": playerid})
                f_private.flush()
                logger.info("Player %s: missing from summaries or private (visibility %s)", playerid, p.get("communityvisibilitystate") if p else "None")
                continue

            players_writer.writerow(
                {
                    "playerid": playerid,
                    "country": p.get("loccountrycode") or "",
                    "created": _unix_to_datetime_string(p.get("timecreated")) or "",
                }
            )
            f_players.flush()

            games = api.get_owned_games(playerid)
            if games is None:
                private_writer.writerow({"playerid": playerid})
                f_private.flush()
                logger.info("Player %s: owned games unavailable (private/invalid)", playerid)
                continue

            appids = [int(g["appid"]) for g in games if "appid" in g]
            library_json = json.dumps(
                [{"appid": g["appid"], "playtime_mins": g.get("playtime_forever", -1)} for g in games if "appid" in g],
                separators=(",", ":")
            )
            purchased_writer.writerow({"playerid": playerid, "library": library_json})
            f_purchased.flush()

            logger.info("Player %s: owned games=%s", playerid, len(appids))

            unlocked_count = 0
            for idx, appid in enumerate(appids):
                achievements = api.get_player_achievements(playerid, appid)
                # Keep the same default pacing as the original script, but configurable.
                time.sleep(achievements_sleep_sec)
                if not achievements:
                    continue
                for ach in achievements:
                    if ach.get("achieved") == 1:
                        unlocked_count += 1
                        history_writer.writerow(
                            {
                                "playerid": playerid,
                                "achievementid": f"{appid}_{ach.get('apiname', '')}",
                                "date_acquired": _unix_to_datetime_string(ach.get("unlocktime")) or "",
                            }
                        )
                f_history.flush()

                if (idx + 1) % 25 == 0:
                    logger.info("Player %s: achievements progress %s/%s apps", playerid, idx + 1, len(appids))

            logger.info("Player %s: unlocked achievements=%s", playerid, unlocked_count)

            # Reviews scraping internally sleeps per page; allow extra pause between players if needed.
            player_reviews = scraper.scrape_reviews(playerid)
            for r in player_reviews:
                reviews_writer.writerow(r)
            f_reviews.flush()
            logger.info("Player %s: reviews=%s", playerid, len(player_reviews))

            if reviews_sleep_sec > 0:
                time.sleep(reviews_sleep_sec)

            logger.info("Player %s: done", playerid)


def _write_manifest(output_dir: Path, extract_dt: str, files: List[Path]) -> None:
    manifest: Dict[str, Any] = {
        "schema_version": "steam_extract_v1",
        "extract_dt": extract_dt,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": {},
    }

    crawler_version = os.getenv("CRAWLER_VERSION")
    if crawler_version:
        manifest["crawler_version"] = crawler_version

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

        logger.info("Wrote %s (rows=%s)", file_path.name, rows)

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Steam crawler that writes partitioned CSV landing drops for Pentaho."
    )
    parser.add_argument(
        "--playerids",
        nargs="+",
        help="One or more Steam64 player IDs.",
    )
    parser.add_argument(
        "--playerids-file",
        type=str,
        help="Path to a text file with one Steam64 ID per line.",
    )
    parser.add_argument(
        "--output-root",
        type=str,
        default="Datasets/landing",
        help="Root folder for landing drops (default: Datasets/landing).",
    )
    parser.add_argument(
        "--extract-dt",
        type=str,
        default=None,
        help="Partition name suffix (default: current UTC time).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Steam Web API key (default: env STEAM_API_KEY or API_KEY).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _setup_logging()
    load_dotenv(override=False)
    args = parse_args(argv)

    api_key = args.api_key or os.getenv("STEAM_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        logger.error("Missing Steam API key: set STEAM_API_KEY (or pass --api-key).")
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

    logger.info("Output directory: %s", output_dir.as_posix())
    logger.info("Partition extract_dt=%s", extract_dt)

    players_csv = output_dir / "players.csv"
    purchased_games_csv = output_dir / "purchased_games.csv"
    history_csv = output_dir / "history.csv"
    reviews_csv = output_dir / "reviews.csv"
    private_csv = output_dir / "private_steamids.csv"

    crawl_all(playerids, api_key, output_dir)

    logger.info("Crawl finished.")

    _write_manifest(output_dir, extract_dt, [players_csv, purchased_games_csv, history_csv, reviews_csv, private_csv])

    (output_dir / "_SUCCESS").write_text("", encoding="utf-8")
    logger.info("Wrote _SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
