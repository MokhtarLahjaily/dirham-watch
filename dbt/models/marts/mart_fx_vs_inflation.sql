-- One row per month from the CPI base year: MAD/EUR and MAD/USD against inflation.
-- FX averages are rebased so the base year averages 100, like the CPI (base 100 = 2017),
-- which puts "how much more a euro costs" and "how much more the basket of goods costs" on
-- one axis.

{%- set base_year = var('rebase_year') %}

with fx as (

    select * from {{ ref('fct_fx_monthly') }}
    where currency_code in ('EUR', 'USD')

),

national_cpi as (

    select * from {{ ref('fct_cpi_yoy') }}
    where is_national and group_code in ('GR', '01')

),

fx_wide as (

    select
        rate_month,
        max(avg_mad_per_unit) filter (where currency_code = 'EUR') as eur_mad,
        max(avg_mad_per_unit) filter (where currency_code = 'USD') as usd_mad,
        max(mom_change) filter (where currency_code = 'EUR') as eur_mad_mom_change,
        max(mom_change) filter (where currency_code = 'USD') as usd_mad_mom_change,
        max(yoy_change) filter (where currency_code = 'EUR') as eur_mad_yoy_change,
        max(yoy_change) filter (where currency_code = 'USD') as usd_mad_yoy_change,
        bool_and(is_month_complete) as is_fx_month_complete
    from fx
    group by rate_month

),

fx_base as (

    select
        avg(eur_mad) as eur_mad_base,
        avg(usd_mad) as usd_mad_base
    from fx_wide
    where extract(year from rate_month) = {{ base_year }}

),

cpi_wide as (

    select
        index_month,
        max(cpi_index) filter (where group_code = 'GR') as cpi_index,
        max(mom_change) filter (where group_code = 'GR') as inflation_mom,
        max(yoy_change) filter (where group_code = 'GR') as inflation_yoy,
        max(yoy_change) filter (where group_code = '01') as food_inflation_yoy
    from national_cpi
    group by index_month

),

months as (

    select generate_series(
        make_date({{ base_year }}, 1, 1),
        greatest(
            (select max(fx_wide.rate_month) from fx_wide),
            (select max(cpi_wide.index_month) from cpi_wide)
        ),
        interval '1 month'
    )::date as report_month

),

rebased as (

    select
        months.report_month,
        fx_wide.eur_mad,
        fx_wide.usd_mad,
        fx_wide.eur_mad_mom_change,
        fx_wide.usd_mad_mom_change,
        fx_wide.eur_mad_yoy_change,
        fx_wide.usd_mad_yoy_change,
        fx_wide.is_fx_month_complete,
        100 * fx_wide.eur_mad / fx_base.eur_mad_base as eur_mad_index,
        100 * fx_wide.usd_mad / fx_base.usd_mad_base as usd_mad_index,
        cpi_wide.cpi_index,
        cpi_wide.inflation_mom,
        cpi_wide.inflation_yoy,
        cpi_wide.food_inflation_yoy
    from months
    cross join fx_base
    left join fx_wide on months.report_month = fx_wide.rate_month
    left join cpi_wide on months.report_month = cpi_wide.index_month

)

select
    report_month,
    eur_mad::numeric(18, 6) as eur_mad,
    usd_mad::numeric(18, 6) as usd_mad,
    eur_mad_mom_change::numeric(12, 6) as eur_mad_mom_change,
    usd_mad_mom_change::numeric(12, 6) as usd_mad_mom_change,
    eur_mad_yoy_change::numeric(12, 6) as eur_mad_yoy_change,
    usd_mad_yoy_change::numeric(12, 6) as usd_mad_yoy_change,
    round(eur_mad_index, 2)::numeric(10, 2) as eur_mad_index,
    round(usd_mad_index, 2)::numeric(10, 2) as usd_mad_index,
    -- Approximation of the dirham's 60/40 EUR/USD basket: weighted mean of the two
    -- rebased indices.
    round(
        {{ var('basket_eur_weight') }} * eur_mad_index
        + {{ var('basket_usd_weight') }} * usd_mad_index,
        2
    )::numeric(10, 2) as basket_index,
    cpi_index::numeric(8, 2) as cpi_index,
    inflation_mom::numeric(12, 6) as inflation_mom,
    inflation_yoy::numeric(12, 6) as inflation_yoy,
    food_inflation_yoy::numeric(12, 6) as food_inflation_yoy,
    coalesce(is_fx_month_complete, false) as is_fx_month_complete,
    cpi_index is not null as has_cpi
from rebased
