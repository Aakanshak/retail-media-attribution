/*
Business question
-----------------
Which active campaigns are materially over- or under-spending relative to their
daily budgets, based on recent behavior rather than a single noisy day?

Why this SQL pattern
--------------------
generate_series creates a complete campaign calendar so zero-spend days are not
silently omitted. A seven-row rolling AVG smooths volatility while retaining
responsiveness. ROW_NUMBER selects the latest observation per campaign, and CASE
translates a continuous pacing ratio into an operational severity.
*/
WITH dataset_boundary AS (
    SELECT max(event_timestamp)::date AS max_event_date
    FROM fact_ad_events
),
campaign_calendar AS (
    SELECT
        c.campaign_id,
        c.campaign_name,
        c.daily_budget,
        calendar_date::date AS spend_date
    FROM dim_campaigns AS c
    CROSS JOIN dataset_boundary AS b
    CROSS JOIN LATERAL generate_series(
        c.start_date,
        least(c.end_date, b.max_event_date),
        interval '1 day'
    ) AS calendar_date
),
daily_spend AS (
    SELECT
        campaign_id,
        event_timestamp::date AS spend_date,
        sum(cost) AS spend
    FROM fact_ad_events
    GROUP BY campaign_id, event_timestamp::date
),
complete_daily_spend AS (
    SELECT
        cc.campaign_id,
        cc.campaign_name,
        cc.daily_budget,
        cc.spend_date,
        coalesce(ds.spend, 0) AS spend
    FROM campaign_calendar AS cc
    LEFT JOIN daily_spend AS ds
        ON ds.campaign_id = cc.campaign_id
       AND ds.spend_date = cc.spend_date
),
rolling_pacing AS (
    SELECT
        *,
        avg(spend) OVER (
            PARTITION BY campaign_id
            ORDER BY spend_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS rolling_7d_avg_spend
    FROM complete_daily_spend
),
latest_campaign_status AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY campaign_id
            ORDER BY spend_date DESC
        ) AS recency_rank
    FROM rolling_pacing
),
classified AS (
    SELECT
        *,
        rolling_7d_avg_spend / NULLIF(daily_budget, 0) AS pacing_ratio,
        CASE
            WHEN rolling_7d_avg_spend / NULLIF(daily_budget, 0) >= 1.50
              OR rolling_7d_avg_spend / NULLIF(daily_budget, 0) <= 0.50
                THEN 'Critical'
            WHEN rolling_7d_avg_spend / NULLIF(daily_budget, 0) >= 1.20
              OR rolling_7d_avg_spend / NULLIF(daily_budget, 0) <= 0.80
                THEN 'Warning'
            ELSE 'On-Track'
        END AS severity,
        CASE
            WHEN rolling_7d_avg_spend > daily_budget THEN 'Over-Pacing'
            WHEN rolling_7d_avg_spend < daily_budget THEN 'Under-Pacing'
            ELSE 'On Budget'
        END AS pacing_status
    FROM latest_campaign_status
    WHERE recency_rank = 1
)
SELECT
    campaign_id,
    campaign_name,
    spend_date,
    round(daily_budget, 2) AS daily_budget,
    round(spend, 2) AS latest_daily_spend,
    round(rolling_7d_avg_spend, 2) AS rolling_7d_avg_spend,
    round(100 * pacing_ratio, 1) AS budget_utilization_pct,
    pacing_status,
    severity
FROM classified
ORDER BY
    CASE severity WHEN 'Critical' THEN 1 WHEN 'Warning' THEN 2 ELSE 3 END,
    abs(pacing_ratio - 1) DESC;

