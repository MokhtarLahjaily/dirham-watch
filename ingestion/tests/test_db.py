"""Load tests against a real Postgres (skipped when WAREHOUSE_PASSWORD is not set).

Each test works in its own throwaway schema, so running them against a warehouse that
already holds data never touches the real `raw` schema.
"""

import dataclasses
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from psycopg import sql

from dirham_watch import db
from dirham_watch.cpi import CpiResource, CpiRow
from dirham_watch.fx import parse_bam

pytestmark = pytest.mark.db

DAY = date(2026, 3, 26)


@pytest.fixture
def schema(db_settings):
    name = f"raw_test_{uuid.uuid4().hex[:12]}"
    yield name
    with db.connect(db_settings) as conn:
        conn.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(name)))


@pytest.fixture
def conn(db_settings, schema):
    with db.connect(db_settings) as connection:
        db.init_schema(connection, schema)
        yield connection


def _count(conn, schema, table):
    query = sql.SQL("select count(*) from {}").format(sql.Identifier(schema, table))
    return conn.execute(query).fetchone()[0]


def test_replace_fx_is_idempotent(conn, schema, bam_payload):
    records = parse_bam(bam_payload)

    db.replace_fx(conn, records, source="bam", start=DAY, end=DAY, schema=schema)
    db.replace_fx(conn, records, source="bam", start=DAY, end=DAY, schema=schema)

    assert _count(conn, schema, "fx_rates") == 58
    eur = conn.execute(
        sql.SQL(
            "select distinct mid_rate, payload->>'libDevise' from {} where currency = 'EUR'"
        ).format(sql.Identifier(schema, "fx_rates"))
    ).fetchall()
    assert [(str(mid), code) for mid, code in eur] == [("10.772900", "EUR")]


def test_replace_fx_scoped_to_currencies_leaves_others(conn, schema, bam_payload):
    db.replace_fx(conn, parse_bam(bam_payload), source="bam", start=DAY, end=DAY, schema=schema)

    db.replace_fx(conn, [], source="bam", start=DAY, end=DAY, currencies=["EUR"], schema=schema)

    assert _count(conn, schema, "fx_rates") == 56


def test_replace_cpi_replaces_the_snapshot_and_records_its_version(conn, schema):
    resource = CpiResource("I4166", "api/I4166", "https://x", datetime(2026, 6, 22, tzinfo=UTC))
    rows = [CpiRow("National", "(GR) GENERAL", "2026M5", date(2026, 5, 1), "120.4")]

    db.replace_cpi(conn, resource, rows * 3, schema=schema)
    db.replace_cpi(conn, resource, rows, schema=schema)

    assert _count(conn, schema, "cpi_index") == 1
    assert db.cpi_loaded_version(conn, "I4166", schema) == ("api/I4166", resource.last_modified)


def test_replace_cpi_clears_rows_from_an_earlier_source(conn, schema):
    old = CpiResource("data_7_5", "xlsx", "https://x", datetime(2025, 2, 6, tzinfo=UTC))
    new = CpiResource("I4166", "api/I4166", "https://y", datetime(2026, 6, 22, tzinfo=UTC))
    row = CpiRow("Rabat", "(GR) GENERAL", "2024M11", date(2024, 11, 1), "153.7")
    db.replace_cpi(conn, old, [row], schema=schema)

    db.replace_cpi(conn, new, [dataclasses.replace(row, index_value="120.1")], schema=schema)

    assert _count(conn, schema, "cpi_index") == 1
    assert db.cpi_loaded_version(conn, "data_7_5", schema) is None


def test_concurrent_fx_loads_do_not_duplicate_rows(db_settings, conn, schema, bam_payload):
    """A second loader waits for the first one's lock instead of racing its delete."""
    records = parse_bam(bam_payload)
    load = {"source": "bam", "start": DAY, "end": DAY, "schema": schema}

    with db.connect(db_settings) as second:
        with conn.transaction():
            db._lock(conn, schema, "fx_rates")
            waiter = threading.Thread(target=db.replace_fx, args=(second, records), kwargs=load)
            waiter.start()
            waiter.join(timeout=1)
            assert waiter.is_alive(), "the second loader should wait for the lock"
            db.replace_fx(conn, records, **load)
        waiter.join(timeout=10)

    assert not waiter.is_alive()
    assert _count(conn, schema, "fx_rates") == len(records)


def test_concurrent_init_schema_does_not_race(db_settings, schema):
    """Parallel `create table if not exists` on a new schema fails without the DDL lock."""

    def init():
        with db.connect(db_settings) as connection:
            db.init_schema(connection, schema)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in [pool.submit(init) for _ in range(8)]:
            future.result()
