-- One row per month, city and product group: index level with month-on-month and
-- year-on-year change. Computed from the published one-decimal indices, so rates can differ
-- from HCP's own releases by about 0.1 point.
-- Series flagged as mislabeled in the source file are left out (see stg_cpi_monthly).

with cpi as (

    select * from {{ ref('stg_cpi_monthly') }}
    where not is_mislabeled_in_source

)

select
    cpi.index_month,
    cpi.city,
    cpi.is_national,
    cpi.group_code,
    cpi.group_level,
    cpi.group_label,
    cpi.cpi_index,
    prev_month.cpi_index as cpi_index_prev_month,
    prev_year.cpi_index as cpi_index_prev_year,
    round(cpi.cpi_index / prev_month.cpi_index - 1, 6)::numeric(12, 6) as mom_change,
    round(cpi.cpi_index / prev_year.cpi_index - 1, 6)::numeric(12, 6) as yoy_change
from cpi
left join cpi as prev_month
    on
        cpi.city = prev_month.city
        and cpi.group_code = prev_month.group_code
        and prev_month.index_month = (cpi.index_month - interval '1 month')::date
left join cpi as prev_year
    on
        cpi.city = prev_year.city
        and cpi.group_code = prev_year.group_code
        and prev_year.index_month = (cpi.index_month - interval '12 months')::date
