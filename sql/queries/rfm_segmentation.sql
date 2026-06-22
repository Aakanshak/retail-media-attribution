/*
Business question
-----------------
Which customers are the most valuable, which are loyal, and which are at risk
of lapsing or already churned?

Why this SQL pattern
--------------------
RFM reduces three behavioral dimensions to interpretable 1-5 scores. NTILE(5)
creates relative quintiles without hard-coding dollar thresholds that become
stale as the business grows. Separate CTEs make the scoring direction explicit:
lower recency is better, while higher frequency and monetary value are better.
*/
WITH analysis_date AS (
    SELECT (max(order_timestamp)::date + 1) AS as_of_date
    FROM fact_orders
),
customer_rfm AS (
    SELECT
        c.customer_id,
        coalesce(a.as_of_date - max(o.order_timestamp)::date, 9999) AS recency_days,
        count(DISTINCT o.order_id) AS frequency,
        coalesce(sum(o.order_total), 0) AS monetary_value
    FROM dim_customers AS c
    CROSS JOIN analysis_date AS a
    LEFT JOIN fact_orders AS o
        ON o.customer_id = c.customer_id
    GROUP BY c.customer_id, a.as_of_date
),
rfm_scores AS (
    SELECT
        customer_id,
        recency_days,
        frequency,
        monetary_value,
        ntile(5) OVER (ORDER BY recency_days DESC) AS recency_score,
        ntile(5) OVER (ORDER BY frequency ASC) AS frequency_score,
        ntile(5) OVER (ORDER BY monetary_value ASC) AS monetary_score
    FROM customer_rfm
),
segmented AS (
    SELECT
        *,
        CASE
            WHEN recency_score >= 4
             AND frequency_score >= 4
             AND monetary_score >= 4
                THEN 'Champions'
            WHEN recency_score >= 3
             AND frequency_score >= 4
                THEN 'Loyal'
            WHEN recency_score <= 2
             AND frequency_score >= 3
                THEN 'At-Risk'
            WHEN recency_score = 1
             AND frequency_score <= 2
                THEN 'Churned'
            ELSE 'Developing'
        END AS customer_segment
    FROM rfm_scores
)
SELECT
    customer_id,
    recency_days,
    frequency,
    round(monetary_value, 2) AS monetary_value,
    recency_score,
    frequency_score,
    monetary_score,
    concat(recency_score, frequency_score, monetary_score) AS rfm_code,
    customer_segment
FROM segmented
ORDER BY
    recency_score DESC,
    frequency_score DESC,
    monetary_score DESC,
    monetary_value DESC;
