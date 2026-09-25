from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tenacity import wait_none

from dirham_watch import http
from dirham_watch.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(http.get.retry, "wait", wait_none())


@pytest.fixture
def bam_payload() -> list[dict]:
    """A real CoursVirement response. BAM returned every currency twice that day.

    Taken from a response recorded by the Frankfurter project's test suite
    (github.com/lineofflight/frankfurter, spec/vcr_cassettes/bam.yml, MIT licence).
    """
    return json.loads((FIXTURES / "bam_cours_virement_2026-03-26.json").read_text())


@pytest.fixture
def db_settings() -> Settings:
    """Settings for a throwaway Postgres; tests using it are skipped when none is reachable."""
    if not os.environ.get("WAREHOUSE_PASSWORD"):
        pytest.skip("WAREHOUSE_PASSWORD not set: no test database")
    psycopg = pytest.importorskip("psycopg")
    settings = Settings.from_env()
    try:
        psycopg.connect(**settings.conninfo(), connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable: {exc}")
    return settings
