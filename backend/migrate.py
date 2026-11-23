"""Apply migrations/*.sql in order, once each. Usage: python migrate.py"""
from pathlib import Path

from sqlalchemy import text

from app.db import get_engine

if __name__ == "__main__":
    with get_engine().begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name VARCHAR PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        done = {r[0] for r in conn.execute(text("SELECT name FROM schema_migrations"))}
        for f in sorted(Path(__file__).parent.joinpath("migrations").glob("*.sql")):
            if f.name in done:
                continue
            conn.exec_driver_sql(f.read_text())
            conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": f.name})
            print("Applied", f.name)
    print("Migrations up to date.")
