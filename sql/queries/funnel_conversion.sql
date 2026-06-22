/*
Business question
-----------------
Where does the advertising funnel lose customers, and how do funnel rates differ
by campaign type and placement?

Why this SQL pattern
--------------------
CTEs separate event classification from rate calculation, making each funnel
stage auditable. Conditional aggregation scans the event fact once instead of
joining the table to itself four times. NULLIF prevents divide-by-zero errors.
*/
WITH funnel_counts AS (
    SELECT
        c.campaign_type,
        e.placement,
        count(*) FILTER (WHERE e.event_type = 'impression') AS impressions,
        count(*) FILTER (WHERE e.event_type = 'click') AS clicks,
        count(*) FILTER (WHERE e.event_type = 'add_to_cart') AS cart_adds,
        count(*) FILTER (WHERE e.event_type = 'purchase') AS purchases
    FROM fact_ad_events AS e
    INNER JOIN dim_campaigns AS c
        ON c.campaign_id = e.campaign_id
    GROUP BY
        c.campaign_type,
        e.placement
),
funnel_rates AS (
    SELECT
        campaign_type,
        placement,
        impressions,
        clicks,
        cart_adds,
        purchases,
        clicks::numeric / NULLIF(impressions, 0) AS impression_to_click_rate,
        cart_adds::numeric / NULLIF(clicks, 0) AS click_to_cart_rate,
        purchases::numeric / NULLIF(cart_adds, 0) AS cart_to_purchase_rate,
        purchases::numeric / NULLIF(impressions, 0) AS overall_conversion_rate
    FROM funnel_counts
)
SELECT
    campaign_type,
    placement,
    impressions,
    clicks,
    cart_adds,
    purchases,
    round(100 * impression_to_click_rate, 3) AS ctr_pct,
    round(100 * click_to_cart_rate, 2) AS click_to_cart_pct,
    round(100 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    round(100 * overall_conversion_rate, 4) AS impression_to_purchase_pct
FROM funnel_rates
ORDER BY impressions DESC;

