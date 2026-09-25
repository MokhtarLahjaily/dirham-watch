-- One row per business day and currency: MAD per 1 unit of foreign currency.

with source as (

    select * from {{ source('raw', 'fx_rates') }}

),

typed as (

    select
        rate_date,
        upper(trim(currency)) as currency_code,
        unit as quote_unit,
        -- Pre-2016 BAM records only carry bid/ask (achat/vente): use their midpoint.
        coalesce(mid_rate, (bid_rate + ask_rate) / 2) / unit as mad_per_unit,
        mid_rate is null as is_mid_derived,
        source as source_system,
        loaded_at,
        case source
            when 'bam' then 1
            when 'frankfurter' then 2
            else 3
        end as source_priority
    from source
    where unit > 0

),

ranked as (

    select
        *,
        -- The API repeats rows on some days, and both sources can hold the same day:
        -- keep the direct BAM value, then the most recent load.
        row_number() over (
            partition by rate_date, currency_code
            order by source_priority asc, loaded_at desc
        ) as row_num
    from typed
    where
        currency_code ~ '^[A-Z]{3}$'
        and mad_per_unit > 0

)

select
    rate_date,
    currency_code,
    round(mad_per_unit, 8)::numeric(18, 8) as mad_per_unit,
    quote_unit,
    is_mid_derived,
    source_system,
    loaded_at
from ranked
where row_num = 1
