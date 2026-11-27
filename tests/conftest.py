from __future__ import annotations

import pytest

from musical_agent.config import get_settings


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    """Deterministic tests never reach a real model: hide any API key from `.env`."""
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
