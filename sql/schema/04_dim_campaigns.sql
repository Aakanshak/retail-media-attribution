CREATE TABLE IF NOT EXISTS dim_campaigns (
    campaign_id varchar(8) PRIMARY KEY,
    advertiser_id varchar(7) NOT NULL
        REFERENCES dim_advertisers (advertiser_id),
    campaign_name varchar(300) NOT NULL,
    campaign_type varchar(30) NOT NULL
        CHECK (
            campaign_type IN (
                'Sponsored Product',
                'Sponsored Brand',
                'Display',
                'Video'
            )
        ),
    start_date date NOT NULL,
    end_date date NOT NULL,
    daily_budget numeric(14, 2) NOT NULL CHECK (daily_budget > 0),
    target_acos numeric(7, 4) NOT NULL CHECK (target_acos > 0),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_dim_campaigns_advertiser_id
    ON dim_campaigns (advertiser_id);
CREATE INDEX IF NOT EXISTS idx_dim_campaigns_active_dates
    ON dim_campaigns (start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_dim_campaigns_type
    ON dim_campaigns (campaign_type);

