-- The BAM API sometimes returns the same currency twice for a day. Staging keeps one row,
-- which is only safe while the duplicates carry the same rate.

{{ config(severity='warn') }}

select
    source,
    rate_date,
    currency,
    count(distinct coalesce(mid_rate, (bid_rate + ask_rate) / 2) / unit) as distinct_rates
from {{ source('raw', 'fx_rates') }}
group by source, rate_date, currency
having count(distinct coalesce(mid_rate, (bid_rate + ask_rate) / 2) / unit) > 1
