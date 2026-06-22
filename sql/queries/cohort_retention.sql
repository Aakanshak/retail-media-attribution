/*
Business question
-----------------
For each customer signup cohort, what percentage returned to purchase in months
1 through 6 after signup?

Why this SQL pattern
--------------------
The customer-to-order join establishes activity relative to each customer's own
cohort month. Conditional aggregation pivots month offsets into the classic
retention triangle. Restricting to fully matured cohorts avoids understating
recent cohorts that have not yet had six months of observation.
*/
WITH data_boundary AS (
    SELECT
        date_trunc('month', min(order_timestamp))::date AS first_order_month,
        date_trunc('month', max(order_timestamp))::date AS last_order_month
    FROM fact_orders
),
customer_cohorts AS (
    SELECT
        c.customer_id,
        date_trunc('month', c.signup_date)::date AS cohort_month
    FROM dim_customers AS c
    CROSS JOIN data_boundary AS b
    WHERE date_trunc('month', c.signup_date)::date >= b.first_order_month
      AND date_trunc('month', c.signup_date)::date
          <= (b.last_order_month - interval '6 months')::date
),
cohort_sizes AS (
    SELECT
        cohort_month,
        count(*) AS cohort_size
    FROM customer_cohorts
    GROUP BY cohort_month
),
customer_purchase_months AS (
    SELECT DISTINCT
        cc.customer_id,
        cc.cohort_month,
        date_trunc('month', o.order_timestamp)::date AS purchase_month
    FROM customer_cohorts AS cc
    INNER JOIN fact_orders AS o
        ON o.customer_id = cc.customer_id
       AND o.order_timestamp >= cc.cohort_month
),
activity_offsets AS (
    SELECT
        customer_id,
        cohort_month,
        (
            extract(year FROM age(purchase_month, cohort_month)) * 12
            + extract(month FROM age(purchase_month, cohort_month))
        )::integer AS month_number
    FROM customer_purchase_months
),
retained_customers AS (
    SELECT
        cohort_month,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 1) AS month_1,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 2) AS month_2,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 3) AS month_3,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 4) AS month_4,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 5) AS month_5,
        count(DISTINCT customer_id) FILTER (WHERE month_number = 6) AS month_6
    FROM activity_offsets
    WHERE month_number BETWEEN 1 AND 6
    GROUP BY cohort_month
)
SELECT
    cs.cohort_month,
    cs.cohort_size,
    round(100.0 * coalesce(r.month_1, 0) / cs.cohort_size, 2) AS month_1_retention_pct,
    round(100.0 * coalesce(r.month_2, 0) / cs.cohort_size, 2) AS month_2_retention_pct,
    round(100.0 * coalesce(r.month_3, 0) / cs.cohort_size, 2) AS month_3_retention_pct,
    round(100.0 * coalesce(r.month_4, 0) / cs.cohort_size, 2) AS month_4_retention_pct,
    round(100.0 * coalesce(r.month_5, 0) / cs.cohort_size, 2) AS month_5_retention_pct,
    round(100.0 * coalesce(r.month_6, 0) / cs.cohort_size, 2) AS month_6_retention_pct
FROM cohort_sizes AS cs
LEFT JOIN retained_customers AS r
    ON r.cohort_month = cs.cohort_month
ORDER BY cs.cohort_month;
