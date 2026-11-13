"""One-time copy of an existing Suji Cafe SQLite database into MySQL.
Run after creating the MySQL schema: python migrate_sqlite_to_mysql.py
Back up suji.db and the target MySQL database first.
"""
import os, sqlite3
import pymysql
from dotenv import load_dotenv
load_dotenv()

SQLITE_FILE = os.path.join(os.path.dirname(__file__), "suji.db")
TABLES = ["users", "otp_codes", "trusted_devices", "products", "orders",
          "order_items", "diy_bookings", "saved_addresses"]

def main():
    if not os.path.exists(SQLITE_FILE):
        raise SystemExit("suji.db was not found. Put your existing SQLite database beside this script.")
    source = sqlite3.connect(SQLITE_FILE)
    source.row_factory = sqlite3.Row
    target = pymysql.connect(host=os.getenv("MYSQL_HOST","127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT","3306")), user=os.getenv("MYSQL_USER","root"),
        password=os.getenv("MYSQL_PASSWORD",""), database=os.getenv("MYSQL_DATABASE","suji_cafe"),
        charset="utf8mb4", autocommit=False)
    try:
        with target.cursor() as cur:
            # Refuse to overwrite existing users/orders. The destination must be empty.
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                if cur.fetchone()[0]:
                    raise SystemExit(f"Target table {table} is not empty. Use a new database; existing data will not be deleted.")
            for table in TABLES:
                try:
                    rows = source.execute(f"SELECT * FROM {table}").fetchall()
                except sqlite3.OperationalError:
                    print(f"Skipping missing source table: {table}")
                    continue
                if not rows:
                    print(f"{table}: 0 rows")
                    continue
                columns = rows[0].keys()
                names = ",".join(f"`{c}`" for c in columns)
                marks = ",".join(["%s"] * len(columns))
                cur.executemany(f"INSERT INTO `{table}` ({names}) VALUES ({marks})",
                                [tuple(row[c] for c in columns) for row in rows])
                print(f"{table}: copied {len(rows)} rows")
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()

if __name__ == "__main__":
    main()
