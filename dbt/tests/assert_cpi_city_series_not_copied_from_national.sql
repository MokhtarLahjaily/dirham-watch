-- Reports city series that repeat a national series of another product group, a defect
-- of the former data.gov.ma source where every city's all-items row held a national
-- sub-index. stg_cpi_monthly flags them and fct_cpi_yoy leaves them out, so this only warns.

{{ config(severity='warn') }}

select
    city,
    group_code,
    group_label,
    count(*) as months
from {{ ref('stg_cpi_monthly') }}
where is_mislabeled_in_source
group by city, group_code, group_label
