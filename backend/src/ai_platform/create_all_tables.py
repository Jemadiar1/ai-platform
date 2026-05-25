"""Create all missing tables from SQLAlchemy models."""
import os
import sys

# Set up the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ai_platform.database import engine, Base
from ai_platform.models.db import (
    Tenant,
    User,
    Task,
    UsageEvent,
    AgentMemory,
    ConversationSession,
    ChannelMapping,
    Message,
    TenantSkill,
    Contact,
)

print("Creating all tables from SQLAlchemy models...")
Base.metadata.create_all(engine)
print("Tables created successfully.")

# List tables
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f"\nTables in database ({len(tables)}):")
for table in sorted(tables):
    print(f"  - {table}")
