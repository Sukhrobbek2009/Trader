"""Record portfolio snapshots on demand. Usage:

    python snapshot.py            # one per user per UTC day (what the server does automatically)
    python snapshot.py --force    # one for every user right now, even if they already have today's
"""
import sys

from sqlalchemy.orm import Session

from app.db import get_engine
from app.valuation import take_daily_snapshots

if __name__ == "__main__":
    force = "--force" in sys.argv[1:]
    with Session(get_engine()) as session:
        n = take_daily_snapshots(session, force=force)
    print(f"Recorded {n} snapshot(s){' (forced)' if force else ''}.")
