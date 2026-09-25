-- One row per month and currency: average, range and end-of-month MAD rate, with
-- month-on-month and year-on-year changes of the monthly average.

with daily as (

    select * from {{ ref('stg_fx_daily') }}

),

monthly as (

    select
        currency_code,
        date_trunc('month', rate_date)::date as rate_month,
        avg(mad_per_unit) as avg_mad_per_unit,
        min(mad_per_unit) as min_mad_per_unit,
        max(mad_per_unit) as max_mad_per_unit,
        count(*) as quoted_days,
        max(rate_date) as last_quote_date
    from daily
    group by currency_code, date_trunc('month', rate_date)

),

month_end as (

    select distinct on (daily.currency_code, date_trunc('month', daily.rate_date))
        daily.currency_code,
        date_trunc('month', daily.rate_date)::date as rate_month,
        daily.mad_per_unit as end_of_month_mad_per_unit
    from daily
    order by
        daily.currency_code asc,
        date_trunc('month', daily.rate_date) asc,
        daily.rate_date desc

),

latest as (

    select max(rate_date) as latest_rate_date from daily

)

select
    monthly.rate_month,
    monthly.currency_code,
    round(monthly.avg_mad_per_unit, 6)::numeric(18, 6) as avg_mad_per_unit,
    monthly.min_mad_per_unit::numeric(18, 8) as min_mad_per_unit,
    monthly.max_mad_per_unit::numeric(18, 8) as max_mad_per_unit,
    month_end.end_of_month_mad_per_unit::numeric(18, 8) as end_of_month_mad_per_unit,
    monthly.quoted_days,
    monthly.last_quote_date,
    -- Changes are fractions (0.012 = +1.2 %). Previous periods are joined by date rather
    -- than lag() so that a missing month yields null instead of a wrong comparison.
    round(monthly.avg_mad_per_unit / prev_month.avg_mad_per_unit - 1, 6)::numeric(12, 6)
        as mom_change,
    round(monthly.avg_mad_per_unit / prev_year.avg_mad_per_unit - 1, 6)::numeric(12, 6)
        as yoy_change,
    -- The newest month in the data is still filling up.
    monthly.rate_month < date_trunc('month', latest.latest_rate_date) as is_month_complete
from monthly
inner join month_end
    on
        monthly.currency_code = month_end.currency_code
        and monthly.rate_month = month_end.rate_month
cross join latest
left join monthly as prev_month
    on
        monthly.currency_code = prev_month.currency_code
        and prev_month.rate_month = (monthly.rate_month - interval '1 month')::date
left join monthly as prev_year
    on
        monthly.currency_code = prev_year.currency_code
        and prev_year.rate_month = (monthly.rate_month - interval '12 months')::date
