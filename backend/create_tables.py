"""Create all tables (idempotent). Usage: python create_tables.py"""
from app import models
from app.db import get_engine

if __name__ == "__main__":
    models.Base.metadata.create_all(get_engine())
    print("Tables ready:", ", ".join(models.Base.metadata.tables))
