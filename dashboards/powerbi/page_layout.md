# Power BI Report Page Specification

## Global design

- Canvas: 16:9.
- Theme: white or very light gray background, dark navy text, restrained accent
  colors.
- Use the same channel colors across every page:
  - Sponsored Product: dark blue
  - Sponsored Brand: teal
  - Display: purple
  - Video: orange
- Place a compact date slicer in the upper-right of pages 1 and 2.
- Add a reset-filters button and page-navigation buttons.
- Keep visual titles phrased as business conclusions or questions.
- Use report-page tooltips for campaign and channel diagnostics.

## Page 1 — Executive Summary

**Business question:** Are retail-media investment and commerce outcomes
improving, and where should leadership focus attention?

### Top row: KPI cards

Use six card visuals:

1. `Ad Spend`
2. `Attributed Revenue`
3. `ROAS`
4. `ACOS`
5. `CTR`
6. `CVR`

Add small reference labels for:

- revenue MoM growth;
- spend MoM growth;
- ROAS MoM growth.

Use conditional colors:

- positive ROAS/revenue growth: green;
- negative growth: red;
- ACOS above the selected campaign target: red.

### Center: performance trend

Visual: line and clustered-column chart.

- X-axis: `DimDate[Date]` at month level
- Columns: `Ad Spend`
- Line: `Attributed Revenue`
- Secondary line or tooltip: `ROAS`
- Analytics annotations: Back-to-School and Holiday promotion periods

### Bottom-left: funnel

Visual: funnel.

- Category: event stage
- Values: Impressions, Clicks, Cart Adds, Ad Purchases
- Tooltip: CTR, click-to-cart rate, cart-to-purchase rate

If the standard funnel visual cannot show campaign type cleanly, use small
multiples or a campaign-type slicer.

### Bottom-right: efficiency by campaign type

Visual: scatter chart.

- X-axis: `Ad Spend`
- Y-axis: `ROAS`
- Bubble size: `Attributed Revenue`
- Legend: `DimCampaign[campaign_type]`
- Details: `DimCampaign[campaign_id]`
- Add a horizontal reference line at ROAS = 1.0

### Page filters and slicers

- Date
- Campaign type
- Advertiser tier
- Region

## Page 2 — Campaign Performance

**Business question:** Which campaigns, brands, and placements are driving
efficient growth, and which require optimization?

### Left rail: slicers

- `DimCampaign[campaign_type]`
- `DimCampaign[advertiser_tier]`
- `DimCampaign[brand_name]`
- `FactAdEvents[placement]`
- `FactAdEvents[device_type]`
- `DimProduct[category]`

Enable search for advertiser and campaign slicers.

### Top row: operational cards

1. Active/selected campaigns
2. Ad Spend
3. Budget Utilization %
4. CPC
5. CPA
6. ROAS

### Main visual: campaign performance matrix

Rows:

- Brand
- Campaign name
- Campaign type

Values:

- Impressions
- Clicks
- CTR
- Ad Purchases
- CVR
- Ad Spend
- Attributed Revenue
- CPC
- CPA
- ROAS
- ACOS
- Budget Variance %

Formatting:

- Data bars for spend and revenue
- Red/amber/green icons for ROAS and budget variance
- Conditional background for ACOS relative to `target_acos`
- Allow drill from brand to campaign

### Secondary visual: monthly campaign trend

Visual: line chart with small multiples by selected campaign or campaign type.

- X-axis: `DimDate[Year Month]`
- Values: ROAS and CTR
- Tooltip: spend, revenue, CVR, MoM growth

### Tertiary visual: placement/device decomposition

Visual: clustered bar chart.

- Axis: placement
- Value: Ad Spend or Ad Purchases
- Legend: device type
- Tooltip: CTR, CVR, ROAS

### Drill-through page behavior

Configure campaign drill-through using `campaign_id`. Include:

- daily spend;
- event funnel;
- product mix;
- budget pacing;
- customer region distribution.

## Page 3 — Attribution Model Comparison

**Business question:** How does budget-allocation guidance change when the
business moves beyond Last Touch?

This is the differentiator page. Keep its visual hierarchy simple and make model
disagreement immediately visible.

### Top row: model controls and cards

Slicer:

- `DimAttributionModel[model]`

Cards:

1. `Attributed Conversions by Model`
2. `Model Attributed Revenue`
3. `Model Attributed ROAS`
4. `Selected Attribution Model`

### Main “wow” visual: grouped channel credit

Visual: clustered column chart.

- X-axis: `DimChannel[channel]`
- Legend: `DimAttributionModel[model]`
- Value: `Attributed Conversions by Model`

Filter the visual to:

- Last Touch
- Linear
- Markov
- Shapley

Sort by Last Touch or total attributed conversions. Use data labels selectively;
the tooltip should show:

- attributed conversions;
- credit share;
- attributed revenue;
- attributed ROAS;
- funnel stage.

### Model-shift visual

Visual: diverging horizontal bar chart.

- Axis: channel
- Value: `Shapley vs Last Touch Credit`
- Positive values: blue/purple
- Negative values: red

This makes channels gaining or losing credit immediately visible.

### Funnel-stage allocation

Visual: 100% stacked column chart.

- X-axis: attribution model
- Legend: funnel stage
- Value: attributed conversions

Use Upper Funnel, Mid Funnel, and Bottom Funnel ordering.

### Interpretation panel

Use a text box with three short points:

- Last Touch identifies where demand was captured.
- Markov measures dependence on journey transitions.
- Shapley estimates average marginal coalition value.

Add a link or reference to `docs/attribution_methodology.md`.

### Page filters

- Attribution model
- Channel
- Funnel stage

Do not add campaign/date slicers unless the attribution output is regenerated at
those grains. The current result table represents the complete modeled snapshot.

## Page 4 — Customer Cohorts and RFM

**Business question:** Which customer groups are retaining, growing in value,
or showing signs of churn?

### Top row: customer cards

1. Purchasing Customers
2. Average Order Value
3. Champions
4. Loyal Customers
5. At-Risk Customers
6. Churned Customers

### Left: cohort retention heatmap

Visual: matrix with conditional formatting.

- Rows: signup cohort month
- Columns: Month 1 through Month 6
- Values: retention percentage
- Background gradient: pale blue to dark blue

Load the output of `sql/queries/cohort_retention.sql` as a dedicated table, then
either retain its wide columns for the matrix or unpivot Month 1–6 in Power
Query for more flexible visuals.

### Right: RFM scatter

Visual: scatter chart.

- X-axis: `DimCustomer[recency_days]`
- Y-axis: `DimCustomer[frequency]`
- Size: `DimCustomer[monetary_value]`
- Legend: `DimCustomer[customer_segment]`
- Details: customer ID

Cap extreme monetary bubble sizes or use logarithmic scaling if a few customers
dominate the visual.

### Bottom-left: segment composition

Visual: horizontal bar chart.

- Axis: customer segment
- Value: `RFM Segment Count`
- Tooltip: average monetary value and average frequency

### Bottom-right: segment revenue

Visual: treemap or stacked column chart.

- Group: customer segment
- Value: Total Revenue
- Tooltip: customers, AOV, frequency

### Page filters

- Signup cohort
- Loyalty tier
- Region
- Device preference
- RFM segment

## Recommended interactions

- Page 1 campaign-type selections should filter all page visuals.
- Page 2 matrix selections should filter trend and placement visuals.
- Page 3 grouped bars should cross-highlight the model-shift visual.
- Page 4 cohort heatmap should not filter the customer-level RFM scatter unless
  the cohort output is modeled at customer grain.
- Disable interactions that create misleading partial denominators.
