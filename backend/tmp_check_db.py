import psycopg2
import urllib.parse as up
from app.config import get_settings
s = get_settings()
print('DB URL', s.database_url)
u = up.urlparse(s.database_url)
conn = psycopg2.connect(dbname=u.path[1:], user=u.username, password=u.password, host=u.hostname, port=u.port, sslmode='require')
cur = conn.cursor()
cur.execute("select table_name from information_schema.tables where table_schema='public'")
print(cur.fetchall())
cur.execute("select column_name, data_type from information_schema.columns where table_name='entreprises'")
print('entreprises', cur.fetchall())
cur.execute("select column_name, data_type from information_schema.columns where table_name='offres'")
print('offres', cur.fetchall())
cur.execute("select column_name, data_type from information_schema.columns where table_name='candidats'")
print('candidats', cur.fetchall())
cur.execute("select column_name, data_type from information_schema.columns where table_name='candidatures'")
print('candidatures', cur.fetchall())
cur.close(); conn.close()
