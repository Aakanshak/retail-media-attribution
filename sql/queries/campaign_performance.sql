/*
Business question
-----------------
How efficiently did each campaign perform each month, and is performance
improving or deteriorating versus the prior month?

Why this SQL pattern
--------------------
Separate CTEs aggregate media and order revenue at their natural grains before
joining, preventing spend or revenue from being duplicated. LAG is the correct
window function for month-over-month comparisons because it preserves every
campaign-month row while exposing the previous observation.
*/
WITH monthly_media AS (
    SELECT
        e.campaign_id,
        date_trunc('month', e.event_timestamp)::date AS performance_month,
        count(*) FILTER (WHERE e.event_type = 'impression') AS impressions,
        count(*) FILTER (WHERE e.event_type = 'click') AS clicks,
        count(*) FILTER (WHERE e.event_type = 'purchase') AS purchases,
        sum(e.cost) AS spend
    FROM fact_ad_events AS e
    GROUP BY
        e.campaign_id,
        date_trunc('month', e.event_timestamp)::date
),
monthly_revenue AS (
    SELECT
        e.campaign_id,
        date_trunc('month', e.event_timestamp)::date AS performance_month,
        sum(o.order_total) AS attributed_revenue
    FROM fact_orders AS o
    INNER JOIN fact_ad_events AS e
        ON e.event_id = o.purchase_event_id
       AND e.event_timestamp = o.order_timestamp
       AND e.event_type = 'purchase'
    WHERE NOT o.is_organic
    GROUP BY
        e.campaign_id,
        date_trunc('month', e.event_timestamp)::date
),
monthly_kpis AS (
    SELECT
        m.campaign_id,
        c.campaign_name,
        c.campaign_type,
        m.performance_month,
        m.impressions,
        m.clicks,
        m.purchases,
        m.spend,
        coalesce(r.attributed_revenue, 0) AS attributed_revenue,
        m.clicks::numeric / NULLIF(m.impressions, 0) AS ctr,
        m.purchases::numeric / NULLIF(m.clicks, 0) AS cvr,
        m.spend / NULLIF(m.clicks, 0) AS cpc,
        coalesce(r.attributed_revenue, 0) / NULLIF(m.spend, 0) AS roas,
        m.spend / NULLIF(coalesce(r.attributed_revenue, 0), 0) AS acos
    FROM monthly_media AS m
    INNER JOIN dim_campaigns AS c
        ON c.campaign_id = m.campaign_id
    LEFT JOIN monthly_revenue AS r
        ON r.campaign_id = m.campaign_id
       AND r.performance_month = m.performance_month
),
with_prior_month AS (
    SELECT
        monthly_kpis.*,
        lag(ctr) OVER campaign_timeline AS prior_month_ctr,
        lag(cvr) OVER campaign_timeline AS prior_month_cvr,
        lag(roas) OVER campaign_timeline AS prior_month_roas,
        lag(acos) OVER campaign_timeline AS prior_month_acos
    FROM monthly_kpis
    WINDOW campaign_timeline AS (
        PARTITION BY campaign_id
        ORDER BY performance_month
    )
)
SELECT
    campaign_id,
    campaign_name,
    campaign_type,
    performance_month,
    impressions,
    clicks,
    purchases,
    round(spend, 2) AS spend,
    round(attributed_revenue, 2) AS attributed_revenue,
    round(100 * ctr, 3) AS ctr_pct,
    round(100 * cvr, 2) AS cvr_pct,
    round(cpc, 2) AS cpc,
    round(roas, 2) AS roas,
    round(100 * acos, 2) AS acos_pct,
    round(100 * (ctr / NULLIF(prior_month_ctr, 0) - 1), 2) AS ctr_mom_pct,
    round(100 * (cvr / NULLIF(prior_month_cvr, 0) - 1), 2) AS cvr_mom_pct,
    round(100 * (roas / NULLIF(prior_month_roas, 0) - 1), 2) AS roas_mom_pct,
    round(100 * (acos / NULLIF(prior_month_acos, 0) - 1), 2) AS acos_mom_pct
FROM with_prior_month
ORDER BY campaign_id, performance_month;
