# Power BI DAX Measures

## Naming and formatting

Create a dedicated empty table called `_Measures` and store all measures there.
Use display folders such as `Funnel`, `Financial`, `Growth`, `Attribution`,
`Customers`, and `RFM`.

Format:

- counts: whole number;
- currency: `$#,0.00`;
- ratios: `0.00x`;
- rates: `0.00%`;
- percentage-point deltas: `+0.00%;-0.00%;0.00%`.

## Core event measures

```DAX
Event Count =
COUNTROWS ( FactAdEvents )
```

```DAX
Impressions =
CALCULATE (
    [Event Count],
    KEEPFILTERS ( FactAdEvents[event_type] = "impression" )
)
```

```DAX
Clicks =
CALCULATE (
    [Event Count],
    KEEPFILTERS ( FactAdEvents[event_type] = "click" )
)
```

```DAX
Cart Adds =
CALCULATE (
    [Event Count],
    KEEPFILTERS ( FactAdEvents[event_type] = "add_to_cart" )
)
```

```DAX
Ad Purchases =
CALCULATE (
    [Event Count],
    KEEPFILTERS ( FactAdEvents[event_type] = "purchase" )
)
```

```DAX
CTR =
DIVIDE ( [Clicks], [Impressions] )
```

```DAX
Click-to-Cart Rate =
DIVIDE ( [Cart Adds], [Clicks] )
```

```DAX
Cart-to-Purchase Rate =
DIVIDE ( [Ad Purchases], [Cart Adds] )
```

```DAX
CVR =
DIVIDE ( [Ad Purchases], [Clicks] )
```

```DAX
Impression-to-Purchase Rate =
DIVIDE ( [Ad Purchases], [Impressions] )
```

## Spend and order measures

```DAX
Ad Spend =
SUM ( FactAdEvents[cost] )
```

```DAX
Total Orders =
DISTINCTCOUNT ( FactOrders[order_id] )
```

```DAX
Units Sold =
SUM ( FactOrders[quantity] )
```

```DAX
Total Revenue =
SUM ( FactOrders[order_total] )
```

```DAX
Attributed Orders =
CALCULATE (
    [Total Orders],
    KEEPFILTERS ( FactOrders[is_organic] = FALSE () )
)
```

```DAX
Attributed Revenue =
CALCULATE (
    [Total Revenue],
    KEEPFILTERS ( FactOrders[is_organic] = FALSE () )
)
```

```DAX
Organic Orders =
CALCULATE (
    [Total Orders],
    KEEPFILTERS ( FactOrders[is_organic] = TRUE () )
)
```

```DAX
Organic Revenue =
CALCULATE (
    [Total Revenue],
    KEEPFILTERS ( FactOrders[is_organic] = TRUE () )
)
```

```DAX
Organic Order Share =
DIVIDE ( [Organic Orders], [Total Orders] )
```

```DAX
Average Order Value =
DIVIDE ( [Total Revenue], [Total Orders] )
```

## Efficiency measures

```DAX
CPC =
DIVIDE ( [Ad Spend], [Clicks] )
```

```DAX
CPA =
DIVIDE ( [Ad Spend], [Ad Purchases] )
```

```DAX
ROAS =
DIVIDE ( [Attributed Revenue], [Ad Spend] )
```

```DAX
ACOS =
DIVIDE ( [Ad Spend], [Attributed Revenue] )
```

```DAX
Gross Profit =
SUMX (
    FactOrders,
    FactOrders[order_total]
        - FactOrders[quantity] * RELATED ( DimProduct[cost_per_unit] )
)
```

```DAX
Gross Margin % =
DIVIDE ( [Gross Profit], [Total Revenue] )
```

```DAX
Contribution After Ad Spend =
[Gross Profit] - [Ad Spend]
```

## Budget measures

These measures use the campaign rows visible in the current filter context and
the count of selected active reporting dates.

```DAX
Selected Days =
COUNTROWS ( VALUES ( DimDate[Date] ) )
```

```DAX
Budget for Selected Period =
SUMX (
    VALUES ( DimCampaign[campaign_id] ),
    CALCULATE ( MAX ( DimCampaign[daily_budget] ) ) * [Selected Days]
)
```

```DAX
Budget Utilization % =
DIVIDE ( [Ad Spend], [Budget for Selected Period] )
```

```DAX
Budget Variance =
[Ad Spend] - [Budget for Selected Period]
```

```DAX
Budget Variance % =
DIVIDE ( [Budget Variance], [Budget for Selected Period] )
```

For exact active-day pacing, create a campaign-date bridge or use the PostgreSQL
budget-pacing query. Multiplying by all selected dates can overstate budget when
a campaign is active for only part of the selected period.

## Month-over-month measures

```DAX
Revenue Previous Month =
CALCULATE (
    [Total Revenue],
    DATEADD ( DimDate[Date], -1, MONTH )
)
```

```DAX
Revenue MoM % Growth =
DIVIDE (
    [Total Revenue] - [Revenue Previous Month],
    [Revenue Previous Month]
)
```

```DAX
Spend Previous Month =
CALCULATE (
    [Ad Spend],
    DATEADD ( DimDate[Date], -1, MONTH )
)
```

```DAX
Spend MoM % Growth =
DIVIDE (
    [Ad Spend] - [Spend Previous Month],
    [Spend Previous Month]
)
```

```DAX
ROAS Previous Month =
CALCULATE (
    [ROAS],
    DATEADD ( DimDate[Date], -1, MONTH )
)
```

```DAX
ROAS MoM % Growth =
DIVIDE (
    [ROAS] - [ROAS Previous Month],
    [ROAS Previous Month]
)
```

```DAX
CTR Previous Month =
CALCULATE (
    [CTR],
    DATEADD ( DimDate[Date], -1, MONTH )
)
```

```DAX
CTR MoM % Growth =
DIVIDE (
    [CTR] - [CTR Previous Month],
    [CTR Previous Month]
)
```

## Customer and journey measures

```DAX
Customers =
DISTINCTCOUNT ( DimCustomer[customer_id] )
```

```DAX
Purchasing Customers =
DISTINCTCOUNT ( FactOrders[customer_id] )
```

```DAX
Converted Journeys =
CALCULATE (
    COUNTROWS ( FactCustomerJourney ),
    KEEPFILTERS ( FactCustomerJourney[conversion_flag] = TRUE () )
)
```

```DAX
Total Journeys =
COUNTROWS ( FactCustomerJourney )
```

```DAX
Journey Conversion Rate =
DIVIDE ( [Converted Journeys], [Total Journeys] )
```

```DAX
Average Touchpoints per Journey =
AVERAGE ( FactCustomerJourney[touchpoint_count] )
```

```DAX
Average Touchpoints per Conversion =
CALCULATE (
    [Average Touchpoints per Journey],
    KEEPFILTERS ( FactCustomerJourney[conversion_flag] = TRUE () )
)
```

## RFM segment measures

The result of `sql/queries/rfm_segmentation.sql` should be merged into
`DimCustomer` on `customer_id` during Power Query refresh.

```DAX
RFM Customers =
CALCULATE (
    DISTINCTCOUNT ( DimCustomer[customer_id] ),
    KEEPFILTERS ( DimCustomer[customer_segment] <> BLANK () )
)
```

```DAX
RFM Segment Count =
DISTINCTCOUNT ( DimCustomer[customer_id] )
```

Use `DimCustomer[customer_segment]` on the visual axis or legend with
`[RFM Segment Count]`.

```DAX
Champions =
CALCULATE (
    [RFM Customers],
    KEEPFILTERS ( DimCustomer[customer_segment] = "Champions" )
)
```

```DAX
Loyal Customers =
CALCULATE (
    [RFM Customers],
    KEEPFILTERS ( DimCustomer[customer_segment] = "Loyal" )
)
```

```DAX
At-Risk Customers =
CALCULATE (
    [RFM Customers],
    KEEPFILTERS ( DimCustomer[customer_segment] = "At-Risk" )
)
```

```DAX
Churned Customers =
CALCULATE (
    [RFM Customers],
    KEEPFILTERS ( DimCustomer[customer_segment] = "Churned" )
)
```

```DAX
Developing Customers =
CALCULATE (
    [RFM Customers],
    KEEPFILTERS ( DimCustomer[customer_segment] = "Developing" )
)
```

```DAX
At-Risk Customer Share =
DIVIDE ( [At-Risk Customers], [RFM Customers] )
```

```DAX
Average Customer Monetary Value =
AVERAGE ( DimCustomer[monetary_value] )
```

```DAX
Average Customer Frequency =
AVERAGE ( DimCustomer[frequency] )
```

## Attribution measures

```DAX
Attributed Conversions by Model =
SUM ( FactAttributionResults[attributed_conversions] )
```

```DAX
Attribution Credit Share =
SUM ( FactAttributionResults[conversion_credit_share] )
```

```DAX
Model Attributed Revenue =
SUM ( FactAttributionResults[attributed_revenue] )
```

```DAX
Model Channel Spend =
SUMX (
    VALUES ( DimChannel[channel] ),
    CALCULATE ( MAX ( FactAttributionResults[spend] ) )
)
```

```DAX
Model Attributed ROAS =
DIVIDE ( [Model Attributed Revenue], [Model Channel Spend] )
```

The following fixed-model measures are useful for the side-by-side matrix and
grouped bar chart:

```DAX
Last Touch Attributed Conversions =
CALCULATE (
    [Attributed Conversions by Model],
    REMOVEFILTERS ( DimAttributionModel ),
    DimAttributionModel[model] = "Last Touch"
)
```

```DAX
Linear Attributed Conversions =
CALCULATE (
    [Attributed Conversions by Model],
    REMOVEFILTERS ( DimAttributionModel ),
    DimAttributionModel[model] = "Linear"
)
```

```DAX
Markov Attributed Conversions =
CALCULATE (
    [Attributed Conversions by Model],
    REMOVEFILTERS ( DimAttributionModel ),
    DimAttributionModel[model] = "Markov"
)
```

```DAX
Shapley Attributed Conversions =
CALCULATE (
    [Attributed Conversions by Model],
    REMOVEFILTERS ( DimAttributionModel ),
    DimAttributionModel[model] = "Shapley"
)
```

```DAX
Markov vs Last Touch Credit =
[Markov Attributed Conversions] - [Last Touch Attributed Conversions]
```

```DAX
Shapley vs Last Touch Credit =
[Shapley Attributed Conversions] - [Last Touch Attributed Conversions]
```

```DAX
Markov vs Last Touch % =
DIVIDE (
    [Markov Attributed Conversions]
        - [Last Touch Attributed Conversions],
    [Last Touch Attributed Conversions]
)
```

```DAX
Selected Attribution Model =
SELECTEDVALUE (
    DimAttributionModel[model],
    "Multiple Models"
)
```

## Optional inactive-date measures

```DAX
Customer Signups =
CALCULATE (
    DISTINCTCOUNT ( DimCustomer[customer_id] ),
    USERELATIONSHIP ( DimDate[Date], DimCustomer[signup_date] )
)
```

```DAX
Campaign Starts =
CALCULATE (
    DISTINCTCOUNT ( DimCampaign[campaign_id] ),
    USERELATIONSHIP ( DimDate[Date], DimCampaign[start_date] )
)
```
