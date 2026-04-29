import os
import re
import ast
import json
import pandas as pd

def main():
    raw_dir = os.path.join("Datasets", "raw")
    min_dir = os.path.join("Datasets", "raw_min")
    os.makedirs(min_dir, exist_ok=True)

    print("Reading history.csv to find top 5 players...")
    history_df = pd.read_csv(os.path.join(raw_dir, 'history.csv'))
    
    # Base criteria: top 5 players with most appearances in history.csv
    top_5_players = history_df['playerid'].value_counts().nlargest(5).index.tolist()
    print(f"Top 5 players identified: {top_5_players}")

    # 1. Filter history.csv
    min_history = history_df[history_df['playerid'].isin(top_5_players)]
    min_history.to_csv(os.path.join(min_dir, 'history.csv'), index=False)
    valid_achievements = min_history['achievementid'].unique()

    # 2. Filter players.csv
    print("Filtering players.csv...")
    players_df = pd.read_csv(os.path.join(raw_dir, 'players.csv'))
    min_players = players_df[players_df['playerid'].isin(top_5_players)]
    min_players.to_csv(os.path.join(min_dir, 'players.csv'), index=False)

    # 3. Filter private_steamids.csv
    print("Filtering private_steamids.csv...")
    private_path = os.path.join(raw_dir, 'private_steamids.csv')
    if os.path.exists(private_path):
        private_df = pd.read_csv(private_path)
        min_private = private_df[private_df['playerid'].isin(top_5_players)]
        min_private.to_csv(os.path.join(min_dir, 'private_steamids.csv'), index=False)

    # 4. Filter reviews.csv
    print("Filtering reviews.csv...")
    reviews_df = pd.read_csv(os.path.join(raw_dir, 'reviews.csv'))
    min_reviews = reviews_df[reviews_df['playerid'].isin(top_5_players)]
    min_reviews.to_csv(os.path.join(min_dir, 'reviews.csv'), index=False)
    valid_games = set(min_reviews['gameid'].unique())

    # 5. Filter purchased_games.csv
    print("Filtering purchased_games.csv...")
    purchased_path = os.path.join(raw_dir, 'purchased_games.csv')
    if os.path.exists(purchased_path):
        purchased_df = pd.read_csv(purchased_path)
        min_purchased = purchased_df[purchased_df['playerid'].isin(top_5_players)]
        min_purchased.to_csv(os.path.join(min_dir, 'purchased_games.csv'), index=False)

        # Attempt to extract gameids from library entries (assuming JSON list of dicts, or strings)
        for lib in min_purchased['library'].dropna():
            # Extract numbers following 'gameid' key if structured as JSON/Dict string
            matches = re.findall(r"['\"]gameid['\"]\s*:\s*(\d+)", str(lib))
            if matches:
                valid_games.update([int(m) for m in matches])
            else:
                raw_nums = re.findall(r"\d+", str(lib))
                valid_games.update([int(m) for m in raw_nums])

    # 6. Filter achievements.csv
    print("Filtering achievements.csv...")
    achievements_df = pd.read_csv(os.path.join(raw_dir, 'achievements.csv'))
    min_achievements = achievements_df[achievements_df['achievementid'].isin(valid_achievements)]
    min_achievements.to_csv(os.path.join(min_dir, 'achievements.csv'), index=False)
    valid_games.update(min_achievements['gameid'].unique())

    # 7. Filter games.csv
    print("Filtering games.csv...")
    games_df = pd.read_csv(os.path.join(raw_dir, 'games.csv'))
    min_games = games_df[games_df['gameid'].isin(valid_games)]
    min_games.to_csv(os.path.join(min_dir, 'games.csv'), index=False)

    print("Minimal dataset created successfully in Datasets/raw_min!")

if __name__ == "__main__":
    main()
