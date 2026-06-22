# Resume-Ready Project Bullets

- Built an end-to-end retail-media analytics platform in Python, PostgreSQL,
  SQLAlchemy, Plotly, and Power BI across 9.0M synthetic ad events, 50K
  customers, 300 campaigns, and 18 months of reproducible data.

- Developed multi-touch attribution models using First/Last Touch, linear and
  time-decay rules, absorbing Markov chains, and exact capped Shapley values;
  found Last Touch assigned 67.2% of credit to bottom-funnel Sponsored Product
  placements versus 45.7% under Shapley, a 21.5-point difference.

- Quantified a hypothetical $4.75K budget-share reallocation on $22.1K of media
  spend by comparing Last Touch with Shapley attribution, while documenting that
  the scenario is observational rather than causal incrementality.

- Engineered a monthly partitioned PostgreSQL event fact and idempotent,
  transactional bulk ETL using batched `COPY`, with schema/type validation,
  rejected-row logging, lineage checks, and row-count integrity tests.

- Delivered six PostgreSQL-backed interactive Plotly analyses and a four-page
  Power BI semantic-model specification covering campaign efficiency,
  attribution, cohort retention, RFM segmentation, and budget-pacing anomalies.

