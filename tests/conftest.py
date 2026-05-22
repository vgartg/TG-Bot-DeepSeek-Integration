"""Pytest bootstrap.

Sets safe defaults for env vars and isolates the SQLite database to an
in-memory store so importing `legal_bot.database` never touches a real DB
file during test collection.
"""
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("PROVIDER_TOKEN", "test-provider")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ADMIN_IDS", "1")
