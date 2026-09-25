-- Bank Al-Maghrib does not quote on weekends; a weekend date points to a parsing or
-- timezone problem upstream.

{{ config(severity='warn') }}

select
    rate_date,
    currency_code
from {{ ref('stg_fx_daily') }}
where extract(isodow from rate_date) > 5
