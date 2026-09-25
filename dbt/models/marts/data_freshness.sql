-- How current each dataset is, evaluated when queried (a view), for the dashboard header.

{{ config(materialized='view') }}

with fx as (

    select max(rate_date) as latest_period from {{ ref('stg_fx_daily') }}

),

cpi as (

    select max(index_month) as latest_period from {{ ref('stg_cpi_monthly') }}

),

lags as (

    select
        'fx_rates' as dataset,
        'Bank Al-Maghrib transfer rates (daily)' as dataset_label,
        fx.latest_period,
        {{ business_days_between('fx.latest_period', as_of_date()) }} as lag,
        'business days' as lag_unit,
        -- Same threshold as the source freshness check in _sources.yml.
        3 as max_lag
    from fx

    union all

    select
        'cpi_index' as dataset,
        'HCP consumer price index (monthly)' as dataset_label,
        cpi.latest_period,
        (
            (extract(year from {{ as_of_date() }}) - extract(year from cpi.latest_period)) * 12
            + extract(month from {{ as_of_date() }}) - extract(month from cpi.latest_period)
        )::int as lag,
        'months' as lag_unit,
        -- HCP publishes a month's index around the 20th of the next month.
        2 as max_lag
    from cpi

)

select
    dataset,
    dataset_label,
    latest_period,
    {{ as_of_date() }} as as_of_date,
    lag,
    lag_unit,
    max_lag,
    coalesce(lag > max_lag, true) as is_stale
from lags
