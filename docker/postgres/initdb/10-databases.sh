#!/usr/bin/env bash
# Runs once, on the first start of an empty Postgres volume.
# Creates one database per concern and a read-only role for Metabase.
# No `set -u`: the Postgres entrypoint sources this file when it is not executable.
set -eo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v warehouse_password="$WAREHOUSE_PASSWORD" \
    -v airflow_password="$AIRFLOW_DB_PASSWORD" \
    -v metabase_password="$METABASE_DB_PASSWORD" \
    -v reader_password="$METABASE_READER_PASSWORD" <<'SQL'
create role dirham login password :'warehouse_password';
create role airflow login password :'airflow_password';
create role metabase login password :'metabase_password';
create role metabase_reader login password :'reader_password';

create database warehouse owner dirham;
create database airflow owner airflow;
create database metabase owner metabase;
SQL

# Schemas are created up front so the reader's default privileges apply to every table dbt
# builds later (dbt runs as `dirham`).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname warehouse <<'SQL'
create schema raw authorization dirham;
create schema staging authorization dirham;
create schema marts authorization dirham;

revoke all on database warehouse from public;
grant connect on database warehouse to metabase_reader;
grant usage on schema staging, marts to metabase_reader;
alter default privileges for role dirham in schema staging grant select on tables to metabase_reader;
alter default privileges for role dirham in schema marts grant select on tables to metabase_reader;
SQL
