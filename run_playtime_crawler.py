import pandas as pd
import subprocess
import os

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    players_csv_path = os.path.join(root_dir, "Datasets", "raw_min", "players.csv")
    
    if not os.path.exists(players_csv_path):
        print(f"Error: {players_csv_path} does not exist.")
        return
        
    print(f"Reading player IDs from {players_csv_path}...")
    df = pd.read_csv(players_csv_path)
    playerids = df['playerid'].dropna().astype(str).tolist()
    
    # We will pass the CSV path to the crawler docker container, since it mounts ./Datasets
    container_csv_path = "Datasets/raw/players.csv"
    
    print(f"Found {len(playerids)} players. Starting playtime crawler via docker-compose...")
    
    # Use python's subprocess to invoke docker compose with the custom entrypoint
    cmd = [
        "docker", "compose", "run", "--rm", "--build",
        "--entrypoint", "python",
        "steam-crawler",
        "-m", "steam_crawler.cli_playtime_update",
        "--playerids"
    ] + playerids
    
    # Note: passing too many IDs via CLI could hit length limits. Better to extract to a txt file in Datasets, and pass --playerids-file
    target_txt_path = os.path.join(root_dir, "Datasets", "raw", "temp_playerids_for_playtime.txt")
    with open(target_txt_path, 'w') as f:
        for pid in playerids:
            f.write(f"{pid}\n")
            
    container_txt_path = "Datasets/raw/temp_playerids_for_playtime.txt"
    
    cmd_file = [
        "docker", "compose", "run", "--rm", "--build",
        "--entrypoint", "python",
        "steam-crawler",
        "-m", "steam_crawler.cli_playtime_update",
        "--playerids-file", container_txt_path
    ]
    
    try:
        subprocess.run(cmd_file, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Crawler failed with exit code: {e.returncode}")
    finally:
        # Cleanup
        if os.path.exists(target_txt_path):
            os.remove(target_txt_path)
            
if __name__ == '__main__':
    main()
