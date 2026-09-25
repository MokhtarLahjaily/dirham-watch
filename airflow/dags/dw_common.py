"""Shared pieces of the Dirham Watch DAGs."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator

START_DATE = pendulum.datetime(2026, 1, 1, tz="UTC")
EXPORT_PATH = "/opt/airflow/exports/rates.json"

DEFAULT_ARGS = {
    "owner": "dirham-watch",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}

# Created by airflow-init with a single slot: dbt runs never overlap across DAGs, so two
# runs can't swap the same tables at once.
DBT_POOL = "dbt"


def dbt(task_id: str, command: str, **kwargs) -> BashOperator:
    """Run a dbt command in the mounted project, installing packages on first use."""
    return BashOperator(
        task_id=task_id,
        bash_command=(
            'cd "$DBT_PROJECT_DIR" '
            '&& { [ -d dbt_packages/dbt_utils ] || "$DBT_BIN" deps; } '
            f'&& "$DBT_BIN" {command}'
        ),
        pool=DBT_POOL,
        **kwargs,
    )
