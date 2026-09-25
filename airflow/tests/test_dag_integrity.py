"""Every DAG imports without errors and has the expected shape."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:  # Airflow >= 3.1
    from airflow.dag_processing.dagbag import DagBag
except ImportError:  # pragma: no cover
    from airflow.models.dagbag import DagBag

DAGS_FOLDER = Path(__file__).resolve().parents[1] / "dags"
# Airflow puts its DAGs folder on sys.path, which is how the DAGs import dw_common.
sys.path.insert(0, str(DAGS_FOLDER))


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_FOLDER))


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}


@pytest.mark.parametrize(
    ("dag_id", "schedule", "tasks"),
    [
        (
            "fx_daily",
            "0 17 * * 1-5",
            {"load_fx", "dbt_source_freshness", "dbt_build", "export_rates"},
        ),
        ("cpi_monthly", "0 6 * * 1", {"load_cpi", "dbt_build", "dbt_source_freshness"}),
        (
            "backfill_history",
            "@once",
            {"init_db", "backfill_fx", "load_cpi", "dbt_build", "export_rates"},
        ),
    ],
)
def test_dag_shape(dagbag, dag_id, schedule, tasks):
    dag = dagbag.dags[dag_id]
    assert dag.schedule == schedule
    assert set(dag.task_ids) == tasks
    assert not dag.catchup


def test_dbt_tasks_share_the_single_slot_pool(dagbag):
    for dag in dagbag.dags.values():
        for task in dag.tasks:
            if task.task_id.startswith("dbt_"):
                assert task.pool == "dbt", f"{dag.dag_id}.{task.task_id}"


def test_exports_only_after_a_successful_build(dagbag):
    for dag_id in ("fx_daily", "backfill_history"):
        export = dagbag.dags[dag_id].get_task("export_rates")
        assert export.upstream_task_ids == {"dbt_build"}
