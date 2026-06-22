CREATE TABLE IF NOT EXISTS dim_advertisers (
    advertiser_id varchar(7) PRIMARY KEY,
    brand_name varchar(200) NOT NULL,
    category varchar(50) NOT NULL,
    tier varchar(20) NOT NULL
        CHECK (tier IN ('Enterprise', 'Mid-Market', 'SMB')),
    join_date date NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dim_advertisers_category
    ON dim_advertisers (category);

