-- The mart must have exactly one row per calendar month, with no gaps.

with ordered as (

    select
        report_month,
        lag(report_month) over (order by report_month) as previous_month
    from {{ ref('mart_fx_vs_inflation') }}

)

select *
from ordered
where
    previous_month is not null
    and report_month <> (previous_month + interval '1 month')::date
