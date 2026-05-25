"""Create all missing tables from SQLAlchemy models."""

import os
import sys

from sqlalchemy import inspect

# Set up the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ai_platform.database import Base, engine

print("Creating all tables from SQLAlchemy models...")
Base.metadata.create_all(engine)
print("Tables created successfully.")

# List tables
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"\nTables in database ({len(tables)}):")
for table in sorted(tables):
    print(f"  - {table}")
