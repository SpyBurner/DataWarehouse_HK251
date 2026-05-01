@echo off
echo "Change steam_crawler/.env to crawl a different set of players"
docker compose build steam-crawler && docker compose run --rm steam-crawler %*
