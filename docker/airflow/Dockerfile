ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION
ARG PYTHON_VERSION

# dbt gets its own virtualenv: its dependency pins conflict with Airflow's constraints.
USER root
RUN mkdir -p /opt/dbt-venv && chown airflow:0 /opt/dbt-venv
USER airflow
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir "dbt-core~=1.12.0" "dbt-postgres~=1.11.0"

# The ingestion package runs inside Airflow tasks, installed against Airflow's constraints.
COPY --chown=airflow:0 ingestion /opt/dirham-watch/ingestion
RUN pip install --no-cache-dir \
    "apache-airflow==${AIRFLOW_VERSION}" \
    /opt/dirham-watch/ingestion \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

ENV DBT_BIN=/opt/dbt-venv/bin/dbt \
    DBT_PROJECT_DIR=/opt/airflow/dbt \
    DBT_PROFILES_DIR=/opt/airflow/dbt
