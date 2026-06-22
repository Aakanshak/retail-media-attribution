CREATE TABLE IF NOT EXISTS fact_customer_journey (
    path_id varchar(12) PRIMARY KEY,
    customer_id varchar(10) NOT NULL
        REFERENCES dim_customers (customer_id),
    product_id varchar(9) NOT NULL
        REFERENCES dim_products (product_id),
    path_start_timestamp timestamp without time zone NOT NULL,
    path_end_timestamp timestamp without time zone NOT NULL,
    ordered_touchpoints jsonb NOT NULL,
    touchpoint_count integer NOT NULL CHECK (touchpoint_count > 0),
    conversion_flag boolean NOT NULL,
    order_id varchar(12)
        REFERENCES fact_orders (order_id),
    lookback_days smallint NOT NULL CHECK (lookback_days > 0),
    CHECK (path_end_timestamp >= path_start_timestamp),
    CHECK (jsonb_typeof(ordered_touchpoints) = 'array'),
    CHECK (jsonb_array_length(ordered_touchpoints) = touchpoint_count),
    CHECK (
        (conversion_flag AND order_id IS NOT NULL)
        OR (NOT conversion_flag AND order_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_fact_journey_customer_id
    ON fact_customer_journey (customer_id);
CREATE INDEX IF NOT EXISTS idx_fact_journey_product_id
    ON fact_customer_journey (product_id);
CREATE INDEX IF NOT EXISTS idx_fact_journey_path_end
    ON fact_customer_journey (path_end_timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_journey_converted
    ON fact_customer_journey (conversion_flag)
    WHERE conversion_flag;
CREATE INDEX IF NOT EXISTS idx_fact_journey_touchpoints_gin
    ON fact_customer_journey USING gin (ordered_touchpoints jsonb_path_ops);

