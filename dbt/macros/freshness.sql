{#- Reference date for freshness: var('as_of_date') when set, otherwise today. -#}
{% macro as_of_date() -%}
    {%- if var('as_of_date', '') -%}
        date '{{ var("as_of_date") }}'
    {%- else -%}
        current_date
    {%- endif -%}
{%- endmacro %}


{#- Weekdays in the half-open interval (start_date, end_date]: 0 when end <= start.
    Moroccan public holidays are not excluded, so a long holiday can raise a false alarm. -#}
{% macro business_days_between(start_date, end_date) -%}
    (
        select count(*)::int
        from generate_series(
            ({{ start_date }})::date + 1,
            ({{ end_date }})::date,
            interval '1 day'
        ) as calendar (day)
        where extract(isodow from calendar.day) < 6
    )
{%- endmacro %}


{#- Custom SQL for `dbt source freshness` on raw.fx_rates (config.loaded_at_query).

    dbt compares max_loaded_at with now() in calendar time. Returning
    now() - <business days since the latest rate> turns its day thresholds into business
    days, so `error_after: 3 days` means "fail when the newest rate is more than 3 business
    days old". An empty table reports the epoch, which is always stale. -#}
{% macro fx_business_day_loaded_at(relation) -%}
    select
        case
            when latest.rate_date is null then timestamptz '1970-01-01'
            else now() - make_interval(
                days => {{ business_days_between('latest.rate_date', as_of_date()) }}
            )
        end as max_loaded_at
    from (select max(rate_date) as rate_date from {{ relation }}) as latest
{%- endmacro %}
