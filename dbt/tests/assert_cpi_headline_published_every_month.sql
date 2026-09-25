-- Every month that has CPI data must include the national all-items index, which the mart
-- relies on.

with months as (

    select distinct index_month from {{ ref('stg_cpi_monthly') }}

),

headline as (

    select index_month
    from {{ ref('stg_cpi_monthly') }}
    where is_national and group_code = 'GR'

)

select months.index_month
from months
left join headline on months.index_month = headline.index_month
where headline.index_month is null
