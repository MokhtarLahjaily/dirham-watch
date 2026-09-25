"""
### Monthly consumer price index

HCP publishes the CPI monthly and updates its statistics database at irregular dates. This
DAG checks the database API weekly and reloads and rebuilds only when HCP's update date for
the indicator moved; an unchanged indicator skips the downstream tasks.
"""

from __future__ import annotations

from airflow.sdk import dag, task
from dw_common import DEFAULT_ARGS, START_DATE, dbt


@dag(
    dag_id="cpi_monthly",
    schedule="0 6 * * 1",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["dirham-watch", "cpi"],
    doc_md=__doc__,
)
def cpi_monthly():
    @task.short_circuit
    def load_cpi() -> bool:
        from dirham_watch.config import Settings
        from dirham_watch.pipeline import load_cpi

        return load_cpi(Settings.from_env())["status"] == "loaded"

    loaded = load_cpi()
    loaded >> [
        dbt("dbt_build", "build --select @stg_cpi_monthly"),
        # Only warns: HCP's database runs a few months behind its monthly releases.
        dbt("dbt_source_freshness", "source freshness --select source:raw.cpi_index"),
    ]


cpi_monthly()
