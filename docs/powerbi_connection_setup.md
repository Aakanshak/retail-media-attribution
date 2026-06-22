# Connect Power BI Desktop to Local PostgreSQL

## Prerequisites

- PostgreSQL is running locally.
- The `retail_media` database exists.
- The schema and data have been loaded:

```powershell
python src\etl\load_to_postgres.py --create-schema
```

- Power BI Desktop is current and uses the same Windows architecture as any
  separately installed provider.

Current Power BI Desktop releases include the PostgreSQL Npgsql provider. If
Power BI still reports that the provider is missing, update Power BI Desktop
first. A separately installed Npgsql version can override the bundled provider,
so remove or align an old GAC-installed provider before troubleshooting the
database itself.

## Connection values

For the default local project configuration:

| Setting | Value |
|---|---|
| Server | `localhost:5432` |
| Database | `retail_media` |
| Authentication | Database |
| Username | Value of `POSTGRES_USER` |
| Password | Value of `POSTGRES_PASSWORD` |

Power BI's PostgreSQL connector asks for server and database separately.

Server format:

```text
hostname:port
```

Local example:

```text
localhost:5432
```

Equivalent URI format used by other PostgreSQL tools:

```text
postgresql://postgres:YOUR_PASSWORD@localhost:5432/retail_media
```

Do not paste the URI into Power BI's Server field; use `localhost:5432` and
enter `retail_media` in the Database field.

## Connect from Power BI Desktop

1. Open Power BI Desktop.
2. Select **Home > Get data > More**.
3. Search for **PostgreSQL database**.
4. Select **Connect**.
5. Enter:
   - Server: `localhost:5432`
   - Database: `retail_media`
6. Open **Advanced options** only if you need a native SQL statement or a
   command timeout.
7. Select **Import** for the recommended portfolio configuration.
8. Select **OK**.
9. Choose **Database** authentication.
10. Enter the PostgreSQL username and password from `.env`.
11. Set the credential level to the local server/database.
12. Select **Connect**.
13. In Navigator, select the required tables, then choose **Transform Data**.

Recommended base tables:

- `dim_advertisers`
- `dim_campaigns`
- `dim_products`
- `dim_customers`
- `fact_ad_events`
- `fact_orders`
- `fact_customer_journey`

Also load the result sets for:

- `sql/queries/rfm_segmentation.sql`
- `sql/queries/cohort_retention.sql`
- attribution model comparison output

## Use a read-only Power BI database user

For a portfolio running only on your laptop, the existing user works. A more
production-like setup uses a dedicated read-only account:

```sql
CREATE ROLE powerbi_reader
LOGIN
PASSWORD 'replace_with_a_strong_password';

GRANT CONNECT ON DATABASE retail_media TO powerbi_reader;
GRANT USAGE ON SCHEMA public TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO powerbi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO powerbi_reader;
```

Use that account in Power BI rather than the database owner.

## Import versus DirectQuery

### Import mode

Power BI copies compressed columnar data into the semantic model.

Advantages:

- Fast visual interactions.
- Full DAX and modeling feature set.
- PostgreSQL is not queried for every click or slicer change.
- The report can be viewed while PostgreSQL is offline after refresh.

Tradeoffs:

- Data is current only as of the last refresh.
- The model consumes local/PBI service memory.
- Refresh must read source changes.

### DirectQuery

Power BI leaves rows in PostgreSQL and sends queries when users interact with
the report.

Advantages:

- Source data remains in PostgreSQL.
- Report interactions can reflect current source data.
- Import-model size limits do not apply in the same way.

Tradeoffs:

- Every visual depends on PostgreSQL query latency and availability.
- Complex pages can generate many concurrent SQL queries.
- DAX/modeling behavior is more constrained.
- Poor source indexing or high-cardinality visuals become immediately visible
  as slow report performance.
- Publishing a report that accesses local PostgreSQL requires an on-premises
  data gateway.

## Recommendation for this project

Use **Import mode**.

The largest table has approximately nine million rows, but Power BI's columnar
compression handles low-cardinality fields such as event type, placement,
device, campaign ID, and product ID efficiently. This is a portfolio analytics
snapshot covering January 2024 through June 2025, not a real-time operational
monitor. Import mode will provide a materially better interview/demo
experience.

Apply these optimizations:

1. Remove unused raw columns before loading.
2. Use integer/decimal/date types rather than text where possible.
3. Keep `ordered_touchpoints` JSON out of the main model.
4. Disable automatic date/time and use the explicit `DimDate`.
5. Use one-way dimension-to-fact relationships.
6. Build measures instead of calculated columns on the 9M-row event fact.
7. Use incremental refresh if the project later grows beyond the current
   18-month snapshot.

Consider DirectQuery only if the requirement becomes near-real-time reporting
or the fact table grows enough that import refresh and model size are no longer
acceptable. Do not choose it merely to signal scale; a senior design chooses the
storage mode that matches latency, freshness, and usability requirements.

## Refresh and publishing

Power BI Desktop can refresh directly while PostgreSQL is running locally.

If the report is published to Power BI Service while PostgreSQL remains on the
local machine:

1. Install the standard on-premises data gateway on a machine that can reach
   PostgreSQL.
2. Keep that machine and PostgreSQL running during refresh.
3. Add a PostgreSQL data source in the gateway using the same server, database,
   and credentials.
4. Map the semantic model to the gateway data source.
5. Configure scheduled refresh.

`localhost` from the Power BI service does not refer to your laptop. The gateway
is the secure bridge between the cloud service and local PostgreSQL.

## Troubleshooting

### Provider missing

- Update Power BI Desktop.
- Confirm 64-bit Power BI is being used.
- Remove conflicting old Npgsql GAC installations.
- Restart Power BI after provider changes.

### Connection refused

- Confirm the PostgreSQL service is running.
- Confirm port `5432`.
- Test the same credentials with `psql`, pgAdmin, or the Python ETL.
- Check `postgresql.conf` and `pg_hba.conf` if connecting from another machine.

### Authentication failed

- Confirm the username/password from `.env`.
- Clear cached credentials under **File > Options and settings > Data source
  settings**, then reconnect.
- Ensure the selected authentication method is Database.

### Slow refresh

- Verify Power Query steps still fold to PostgreSQL.
- Filter dates and remove columns before expensive transformations.
- Import pre-aggregated RFM/cohort result sets instead of recalculating them in
  Power Query.
- Keep indexes and PostgreSQL statistics current.

## Official references

- [Power Query PostgreSQL connector](https://learn.microsoft.com/en-us/power-query/connectors/postgresql)
- [DirectQuery in Power BI](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-directquery-about)
- [DirectQuery model guidance](https://learn.microsoft.com/en-us/power-bi/guidance/directquery-model-guidance)
- [Power BI semantic model storage modes](https://learn.microsoft.com/en-us/power-bi/connect-data/service-dataset-modes-understand)
- [On-premises data gateway](https://learn.microsoft.com/en-us/power-bi/connect-data/service-gateway-onprem)

