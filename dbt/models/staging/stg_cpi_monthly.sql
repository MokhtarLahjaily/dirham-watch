-- One row per month, city and product group: HCP consumer price index, base 100 = 2017.

with source as (

    select * from {{ source('raw', 'cpi_index') }}

),

parsed as (

    select
        period_month as index_month,
        city,
        city = 'National' as is_national,
        -- Labels look like '(GR) GENERAL', '(01) PRODUITS ALIMENTAIRES ...', '(0111) PAIN ...'
        substring(product_group from '^\(([0-9A-Z]+)\)') as group_code,
        trim(regexp_replace(product_group, '^\([0-9A-Z]+\)\s*', '')) as group_label,
        case
            when index_value ~ '^[0-9]+(\.[0-9]+)?$' then index_value::numeric(8, 2)
        end as cpi_index,
        loaded_at
    from source

),

deduplicated as (

    select *
    from (
        select
            *,
            row_number() over (
                partition by index_month, city, group_code
                order by loaded_at desc
            ) as row_num
        from parsed
        where cpi_index is not null
    ) as ranked
    where row_num = 1

),

series as (

    select
        city,
        is_national,
        group_code,
        string_agg(cpi_index::text, ',' order by index_month) as signature,
        count(distinct cpi_index) as distinct_values
    from deduplicated
    group by city, is_national, group_code

),

-- Safeguard against a defect seen in the data.gov.ma export of this index, where each
-- city's '(GR) GENERAL' row repeated a national sub-index (Rabat's was national oils and
-- fats). A city series identical to a national series of another product group is flagged
-- and kept out of the marts. HCP's own API has no such rows today. Constant series are
-- ignored: many groups sit at exactly 100 everywhere.
mislabeled as (

    select distinct
        city_series.city,
        city_series.group_code
    from series as city_series
    inner join series as national_series
        on
            city_series.signature = national_series.signature
            and city_series.group_code <> national_series.group_code
    where
        not city_series.is_national
        and national_series.is_national
        and city_series.distinct_values > 1

)

select
    deduplicated.index_month,
    deduplicated.city,
    deduplicated.is_national,
    deduplicated.group_code,
    -- GR = all items, 2 digits = division, 3 = group, 4 = class
    case
        when deduplicated.group_code = 'GR' then 0
        else length(deduplicated.group_code) - 1
    end as group_level,
    deduplicated.group_label,
    deduplicated.cpi_index::numeric(8, 2) as cpi_index,
    mislabeled.city is not null as is_mislabeled_in_source,
    deduplicated.loaded_at
from deduplicated
left join mislabeled
    on
        deduplicated.city = mislabeled.city
        and deduplicated.group_code = mislabeled.group_code
