# Run migration
Set-Location "C:\Users\Jesús Díaz\Documents\AI-Platform"

$pythonScript = @'
import sys
sys.path.insert(0, "backend/src")

from sqlalchemy import create_engine, text
from ai_platform.core.config import get_settings
from ai_platform.database import Base

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

print("Checking DB connection...")
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("DB connected successfully")
except Exception as e:
    print(f"DB connection failed: {e}")
    sys.exit(1)

# Check if tables exist
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """))
    tables = [row[0] for row in result.fetchall()]
    print(f"Existing tables: {tables}")

# Create all tables (idempotent - won't fail if they exist)
print("Creating tables...")
Base.metadata.create_all(engine)
print("Tables ready!")

# Check again
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """))
    tables = [row[0] for row in result.fetchall()]
    print(f"All tables: {tables}")
'@

python -c $pythonScript
