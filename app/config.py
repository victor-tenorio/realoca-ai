"""Environment-only configuration; .env loading is explicit in PowerShell."""
import os
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./realoca.db")
DEMO_REFERENCE_DATE = date.fromisoformat(os.getenv("DEMO_REFERENCE_DATE", "2026-11-08"))
