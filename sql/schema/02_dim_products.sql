CREATE TABLE IF NOT EXISTS dim_products (
    product_id varchar(9) PRIMARY KEY,
    advertiser_id varchar(7) NOT NULL
        REFERENCES dim_advertisers (advertiser_id),
    product_name varchar(200) NOT NULL,
    category varchar(50) NOT NULL,
    subcategory varchar(80) NOT NULL,
    base_price numeric(12, 2) NOT NULL CHECK (base_price > 0),
    cost_per_unit numeric(12, 2) NOT NULL
        CHECK (cost_per_unit >= 0 AND cost_per_unit <= base_price)
);

CREATE INDEX IF NOT EXISTS idx_dim_products_advertiser_id
    ON dim_products (advertiser_id);
CREATE INDEX IF NOT EXISTS idx_dim_products_category_subcategory
    ON dim_products (category, subcategory);

