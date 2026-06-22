/*
Business question
-----------------
For the same product and month, did customers exposed to retail-media ads convert
at a higher rate than customers in the unexposed holdout group?

Why this SQL pattern
--------------------
CTEs explicitly define treatment, control, and conversion populations before
combining rates. This makes denominator choices visible and reviewable.

Important limitation
--------------------
This is a descriptive incrementality proxy, not a causal estimate. Even with a
holdout, exposure intensity, product demand, customer eligibility, and product
availability may differ. A production experiment should randomly assign eligible
customers before exposure, enforce treatment, and estimate uncertainty.
*/
WITH product_months AS (
    SELECT DISTINCT
        product_id,
        date_trunc('month', event_timestamp)::date AS analysis_month
    FROM fact_ad_events
    WHERE event_type = 'impression'
),
ever_exposed_customers AS (
    SELECT DISTINCT customer_id
    FROM fact_ad_events
),
analysis_months AS (
    SELECT DISTINCT analysis_month
    FROM product_months
),
control_population AS (
    SELECT
        am.analysis_month,
        count(*) AS control_customers
    FROM analysis_months AS am
    INNER JOIN dim_customers AS c
        ON c.signup_date < (am.analysis_month + interval '1 month')
    LEFT JOIN ever_exposed_customers AS e
        ON e.customer_id = c.customer_id
    WHERE e.customer_id IS NULL
    GROUP BY am.analysis_month
),
exposed_population AS (
    SELECT
        product_id,
        date_trunc('month', event_timestamp)::date AS analysis_month,
        count(DISTINCT customer_id) AS exposed_customers
    FROM fact_ad_events
    WHERE event_type = 'impression'
    GROUP BY
        product_id,
        date_trunc('month', event_timestamp)::date
),
exposed_converters AS (
    SELECT
        exposure.product_id,
        exposure.analysis_month,
        count(DISTINCT exposure.customer_id) AS exposed_converters
    FROM (
        SELECT DISTINCT
            product_id,
            customer_id,
            date_trunc('month', event_timestamp)::date AS analysis_month
        FROM fact_ad_events
        WHERE event_type = 'impression'
    ) AS exposure
    INNER JOIN fact_orders AS o
        ON o.customer_id = exposure.customer_id
       AND o.product_id = exposure.product_id
       AND date_trunc('month', o.order_timestamp)::date = exposure.analysis_month
    GROUP BY exposure.product_id, exposure.analysis_month
),
control_converters AS (
    SELECT
        o.product_id,
        date_trunc('month', o.order_timestamp)::date AS analysis_month,
        count(DISTINCT o.customer_id) AS control_converters
    FROM fact_orders AS o
    LEFT JOIN ever_exposed_customers AS e
        ON e.customer_id = o.customer_id
    WHERE e.customer_id IS NULL
    GROUP BY
        o.product_id,
        date_trunc('month', o.order_timestamp)::date
),
group_rates AS (
    SELECT
        pm.product_id,
        pm.analysis_month,
        ep.exposed_customers,
        coalesce(ec.exposed_converters, 0) AS exposed_converters,
        cp.control_customers,
        coalesce(cc.control_converters, 0) AS control_converters,
        coalesce(ec.exposed_converters, 0)::numeric
            / NULLIF(ep.exposed_customers, 0) AS exposed_conversion_rate,
        coalesce(cc.control_converters, 0)::numeric
            / NULLIF(cp.control_customers, 0) AS control_conversion_rate
    FROM product_months AS pm
    INNER JOIN exposed_population AS ep
        ON ep.product_id = pm.product_id
       AND ep.analysis_month = pm.analysis_month
    INNER JOIN control_population AS cp
        ON cp.analysis_month = pm.analysis_month
    LEFT JOIN exposed_converters AS ec
        ON ec.product_id = pm.product_id
       AND ec.analysis_month = pm.analysis_month
    LEFT JOIN control_converters AS cc
        ON cc.product_id = pm.product_id
       AND cc.analysis_month = pm.analysis_month
)
SELECT
    gr.product_id,
    p.product_name,
    gr.analysis_month,
    gr.exposed_customers,
    gr.exposed_converters,
    gr.control_customers,
    gr.control_converters,
    round(100 * gr.exposed_conversion_rate, 4) AS exposed_conversion_pct,
    round(100 * gr.control_conversion_rate, 4) AS control_conversion_pct,
    round(
        100 * (gr.exposed_conversion_rate - gr.control_conversion_rate),
        4
    ) AS absolute_lift_percentage_points,
    round(
        100 * (
            gr.exposed_conversion_rate
            / NULLIF(gr.control_conversion_rate, 0)
            - 1
        ),
        2
    ) AS relative_lift_pct
FROM group_rates AS gr
INNER JOIN dim_products AS p
    ON p.product_id = gr.product_id
ORDER BY gr.analysis_month, relative_lift_pct DESC NULLS LAST;
