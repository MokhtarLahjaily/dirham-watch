"""
### Daily exchange rates

Loads Bank Al-Maghrib transfer rates for the last 7 days (re-fetching a window makes missed
runs heal themselves), checks source freshness in business days, rebuilds the FX models and
exports `rates.json`.

Runs on weekdays at 17:00 UTC: BAM publishes around 12:30 Morocco time and the keyless
mirror picks the rates up between 14:00 and 16:30 UTC.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from dw_common import DEFAULT_ARGS, EXPORT_PATH, START_DATE, dbt

LOOKBACK_DAYS = 7


@dag(
    dag_id="fx_daily",
    schedule="0 17 * * 1-5",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["dirham-watch", "fx"],
    doc_md=__doc__,
)
def fx_daily():
    @task
    def load_fx(**context) -> dict:
        from dirham_watch.config import Settings
        from dirham_watch.pipeline import load_fx

        interval_end = context.get("data_interval_end")
        end = (interval_end or pendulum.now("UTC")).date()
        return load_fx(Settings.from_env(), end - timedelta(days=LOOKBACK_DAYS), end)

    @task
    def export_rates() -> dict:
        from pathlib import Path

        from dirham_watch.config import Settings
        from dirham_watch.pipeline import export_rates

        return export_rates(Settings.from_env(), Path(EXPORT_PATH))

    loaded = load_fx()
    # Fails the run when the newest rate is more than 3 business days old.
    freshness = dbt("dbt_source_freshness", "source freshness --select source:raw.fx_rates")
    # `@` adds the other parents of every descendant: the mart also needs the CPI models.
    build = dbt("dbt_build", "build --select @stg_fx_daily")

    loaded >> [freshness, build]
    build >> export_rates()


fx_daily()
