import os

import pytest

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "0" * 43 + "=")
os.environ["LLM_API_KEY"] = "test-key"


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own sqlite file and a fresh engine."""
    from app import config
    from app.db import base

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    config.get_settings.cache_clear()
    await base.dispose()
    await base.init_db()
    yield
    await base.dispose()
    config.get_settings.cache_clear()
