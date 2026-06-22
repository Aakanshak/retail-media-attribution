/*
Monthly range partitioning allows PostgreSQL to prune irrelevant partitions for
date-filtered analysis and keeps index maintenance bounded as the fact grows.

PostgreSQL requires every UNIQUE/PRIMARY KEY on a partitioned table to contain
the partition key. The physical PK is therefore (event_id, event_timestamp).
event_id remains logically unique in the source and has a separate lookup index.
*/
CREATE TABLE IF NOT EXISTS fact_ad_events (
    event_id varchar(13) NOT NULL,
    campaign_id varchar(8) NOT NULL
        REFERENCES dim_campaigns (campaign_id),
    customer_id varchar(10) NOT NULL
        REFERENCES dim_customers (customer_id),
    product_id varchar(9) NOT NULL
        REFERENCES dim_products (product_id),
    event_timestamp timestamp without time zone NOT NULL,
    event_type varchar(20) NOT NULL
        CHECK (event_type IN ('impression', 'click', 'add_to_cart', 'purchase')),
    placement varchar(30) NOT NULL
        CHECK (
            placement IN (
                'search_top',
                'search_carousel',
                'product_page',
                'category_page',
                'offsite_display'
            )
        ),
    device_type varchar(10) NOT NULL
        CHECK (device_type IN ('mobile', 'desktop', 'tablet')),
    cost numeric(14, 6) NOT NULL CHECK (cost >= 0),
    PRIMARY KEY (event_id, event_timestamp)
) PARTITION BY RANGE (event_timestamp);

CREATE TABLE IF NOT EXISTS fact_ad_events_2024_01
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_02
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_03
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_04
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_05
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_06
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_07
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_08
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_09
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_10
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_11
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2024_12
    PARTITION OF fact_ad_events FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_01
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_02
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_03
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_04
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_05
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE IF NOT EXISTS fact_ad_events_2025_06
    PARTITION OF fact_ad_events FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');

-- Safety net for future or malformed date ranges; monitor this partition.
CREATE TABLE IF NOT EXISTS fact_ad_events_default
    PARTITION OF fact_ad_events DEFAULT;

-- Parent indexes create matching partitioned indexes on every monthly child.
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_event_id
    ON fact_ad_events (event_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_campaign_id
    ON fact_ad_events (campaign_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_customer_id
    ON fact_ad_events (customer_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_product_id
    ON fact_ad_events (product_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_event_timestamp
    ON fact_ad_events (event_timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_campaign_funnel_time
    ON fact_ad_events (campaign_id, event_type, event_timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_ad_events_customer_product_time
    ON fact_ad_events (customer_id, product_id, event_timestamp);

