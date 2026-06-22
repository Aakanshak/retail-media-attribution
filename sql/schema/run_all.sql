\set ON_ERROR_STOP on

BEGIN;

\ir 01_dim_advertisers.sql
\ir 02_dim_products.sql
\ir 03_dim_customers.sql
\ir 04_dim_campaigns.sql
\ir 05_fact_ad_events.sql
\ir 06_fact_orders.sql
\ir 07_fact_customer_journey.sql

COMMIT;

