CREATE TABLE IF NOT EXISTS fact_orders (
    order_id varchar(12) PRIMARY KEY,
    customer_id varchar(10) NOT NULL
        REFERENCES dim_customers (customer_id),
    order_timestamp timestamp without time zone NOT NULL,
    product_id varchar(9) NOT NULL
        REFERENCES dim_products (product_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    order_total numeric(14, 2) NOT NULL CHECK (order_total > 0),
    is_organic boolean NOT NULL,
    purchase_event_id varchar(13),
    FOREIGN KEY (purchase_event_id, order_timestamp)
        REFERENCES fact_ad_events (event_id, event_timestamp),
    CHECK (
        (is_organic AND purchase_event_id IS NULL)
        OR (NOT is_organic AND purchase_event_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_fact_orders_customer_id
    ON fact_orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_product_id
    ON fact_orders (product_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_order_timestamp
    ON fact_orders (order_timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_orders_purchase_event_id
    ON fact_orders (purchase_event_id)
    WHERE purchase_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fact_orders_customer_time
    ON fact_orders (customer_id, order_timestamp);
