CREATE TABLE IF NOT EXISTS dim_customers (
    customer_id varchar(10) PRIMARY KEY,
    signup_date date NOT NULL,
    loyalty_tier varchar(20) NOT NULL
        CHECK (loyalty_tier IN ('Bronze', 'Silver', 'Gold', 'Platinum')),
    region varchar(20) NOT NULL
        CHECK (region IN ('Northeast', 'Midwest', 'South', 'West')),
    device_preference varchar(10) NOT NULL
        CHECK (device_preference IN ('mobile', 'desktop', 'tablet'))
);

CREATE INDEX IF NOT EXISTS idx_dim_customers_signup_date
    ON dim_customers (signup_date);
CREATE INDEX IF NOT EXISTS idx_dim_customers_region_tier
    ON dim_customers (region, loyalty_tier);

