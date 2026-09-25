"""
### Backfill history

Runs once on the first start of the stack, and on demand afterwards: creates the raw
tables, loads FX rates from `FX_BACKFILL_START` (or the `fx_start` parameter) to today,
reloads the full CPI from HCP's API, then builds and tests every dbt model.

History goes through `FX_BACKFILL_SOURCE`, the keyless mirror of the BAM series by default:
one request per currency, about a minute. The BAM API allows 5 calls per minute and needs one
per business day, about 15 hours for 2010 to today; `fx_daily` then keeps the recent days on
the BAM API itself when a key is set, and staging prefers those rows.
"""

from __future__ import annotations

from datetime import date

import pendulum
from airflow.sdk import Param, dag, task
from dw_common import DEFAULT_ARGS, EXPORT_PATH, START_DATE, dbt


@dag(
    dag_id="backfill_history",
    schedule="@once",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["dirham-watch", "backfill"],
    doc_md=__doc__,
    params={
        "fx_start": Param(
            None,
            type=["null", "string"],
            format="date",
            description="First FX date (default: FX_BACKFILL_START)",
        ),
        "fx_end": Param(
            None,
            type=["null", "string"],
            format="date",
            description="Last FX date (default: today)",
        ),
    },
)
def backfill_history():
    @task
    def init_db() -> None:
        from dirham_watch.config import Settings
        from dirham_watch.pipeline import init_db

        init_db(Settings.from_env())

    @task
    def backfill_fx(params: dict | None = None) -> dict:
        from dirham_watch.config import Settings
        from dirham_watch.pipeline import load_fx

        settings = Settings.from_env()
        params = params or {}
        start = date.fromisoformat(params["fx_start"]) if params.get("fx_start") else None
        end = (
            date.fromisoformat(params["fx_end"])
            if params.get("fx_end")
            else pendulum.now("UTC").date()
        )
        return load_fx(
            settings, start or settings.fx_backfill_start, end, source=settings.fx_backfill_source
        )

    @task
    def load_cpi() -> dict:
        from dirham_watch.config import Settings
        from dirham_watch.pipeline import load_cpi

        return load_cpi(Settings.from_env(), force=True)

    @task
    def export_rates() -> dict:
        from pathlib import Path

        from dirham_watch.config import Settings
        from dirham_watch.pipeline import export_rates

        return export_rates(Settings.from_env(), Path(EXPORT_PATH))

    build = dbt("dbt_build", "build")
    init_db() >> [backfill_fx(), load_cpi()] >> build >> export_rates()


backfill_history()
