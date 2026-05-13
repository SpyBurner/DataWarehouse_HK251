from sqlalchemy import create_engine
import pandas as pd
import os, urllib.parse
host = os.getenv('DB_HOST', 'postgres')
port = os.getenv('DB_PORT', '5432')
user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', '31082004@Lmao')
encoded_password = urllib.parse.quote_plus(password)
dbname = os.getenv('DB_NAME', 'Warehouse')
conn_str = f'postgresql+psycopg2://{user}:{encoded_password}@{host}:{port}/{dbname}'
engine = create_engine(conn_str)
df = pd.read_sql('''
    SELECT p.playerid, 
           COALESCE(json_agg(json_build_object('appid', l.appid, 'playtime_mins', l.playtime_mins)) 
           FILTER (WHERE l.appid IS NOT NULL), '[]')::text AS library
    FROM dw.dim_player p
    LEFT JOIN dw.fact_library l ON p.playerid = l.playerid
    WHERE p.is_private = FALSE
    GROUP BY p.playerid
    LIMIT 100
''', engine)
for i in range(5):
    print(df['library'].iloc[i][:200])
