# Attribution Methodology

## Purpose

This attribution layer estimates how much conversion and revenue credit each
retail-media channel should receive. It is designed for decision support:
budget allocation, campaign evaluation, and understanding how awareness media
assists lower-funnel conversion.

No attribution model reveals the single objectively correct answer. Each model
encodes assumptions about how marketing works. The practical standard is to
compare models, understand why they disagree, and validate major budget
decisions with controlled incrementality tests.

## Unit of analysis

The input is one customer-product journey ending in either:

- a purchase; or
- a 14-day timeout with no purchase.

Only impressions and clicks are credit-bearing marketing touches. Add-to-cart
and purchase events are outcomes, so assigning them marketing credit would
confuse funnel progression with media influence.

The default channel grain is:

`campaign_type | placement`

Examples include `Sponsored Product | search_top` and
`Video | offsite_display`. The comparison runner can also operate at campaign
type or placement grain.

## Rule-based models

### First Touch

First Touch gives all credit to the first marketing interaction in a converted
journey.

Use it when the business question is customer discovery: which channel first
introduced the shopper to the product?

Advantages:

- Simple to explain and audit.
- Useful for acquisition and awareness reporting.
- Stable even with relatively little data.

Limitations:

- Ignores every later interaction.
- Can over-credit broad-reach media that starts many journeys.
- Does not use non-converting paths.

### Last Touch

Last Touch gives all credit to the final marketing interaction before purchase.

Use it for operational conversion reporting when a simple, deterministic rule
is required.

Advantages:

- Easy to reproduce.
- Closely connected to the final action.
- Common enough to benchmark against existing reporting systems.

Limitations:

- Systematically favors bottom-funnel search and sponsored-product placements.
- Treats prior awareness and consideration touches as having no value.
- Optimizing only to Last Touch can move budget away from media that creates
  demand and toward media that merely captures existing demand.

### Linear

Linear attribution divides credit equally across all impressions and clicks in
the converted path.

Use it as a neutral multi-touch baseline when there is not enough evidence to
estimate different channel effects.

Advantages:

- Every observed touch receives credit.
- Transparent and deterministic.
- Useful as a sanity-check benchmark.

Limitations:

- Assumes all touches are equally influential.
- A low-intent impression receives the same credit as a high-intent click.
- Does not use non-converting journeys.

### Time Decay

Time Decay assigns exponentially more weight to touches nearer the purchase.
The implementation uses a seven-day half-life:

`weight = exp(-ln(2) * days_before_conversion / 7)`

A touch seven days before conversion therefore receives half the raw weight of
a touch immediately before conversion.

Use it for short buying cycles where recent interactions are believed to carry
more intent, but earlier assists should not be ignored.

Advantages:

- More realistic than Last Touch for multi-step paths.
- The half-life has a clear business interpretation.
- Still easy to calculate and audit.

Limitations:

- The half-life is an assumption, not a learned causal effect.
- Still uses only converted journeys.
- Can continue to favor lower-funnel interactions.

## Markov-chain attribution

The Markov model treats the journey as movement between states:

`Start -> channel -> channel -> Conversion or Null/No Conversion`

Consecutive duplicate channels are collapsed. For example, an impression and
click on the same placement become one state visit rather than an artificial
self-loop.

Transition probabilities are estimated from observed counts:

`P(j | i) = transitions from i to j / all transitions leaving i`

Conversion and Null are absorbing states. If `Q` is the transient-to-transient
transition matrix and `R` is the transient-to-absorbing matrix, eventual
absorption probabilities are:

`B = (I - Q)^-1 R`

The implementation uses `numpy.linalg.solve(I - Q, R)` rather than explicitly
calculating the inverse because solving the linear system is numerically more
stable.

### Removal effect

Each channel is removed from the graph in turn. Probability that previously
entered the removed state is redirected to Null, representing demand that
cannot simply jump over the missing channel. The model recalculates conversion
probability, and the reduction from baseline is the channel's removal effect.
Positive effects are normalized to sum to 100% attribution credit.

Use Markov attribution when there are enough converted and non-converted paths
to estimate journey transitions and when sequence matters.

Advantages:

- Learns from both converting and non-converting journeys.
- Measures channel importance through a counterfactual graph operation.
- Accounts for sequence and interaction between channels.

Limitations:

- A first-order chain assumes the next step depends only on the current state.
- Results depend on channel granularity and the removal counterfactual.
- It is observational attribution, not proof of causal incrementality.
- Rare channels can have unstable transition estimates.

In this synthetic dataset, Markov moves upper-funnel credit only modestly above
Last Touch. That is a valid result: the observed graph contains a large volume
of bottom-funnel traffic. A model should not be altered merely to produce a
preferred narrative.

## Shapley-value attribution

Shapley attribution treats channels as players in a cooperative game. A
coalition is a set of channels available in a journey. The value of a coalition
is its smoothed observed conversion rate. A channel's Shapley value is its
average marginal contribution across every coalition it could join:

`phi_i = sum_S weight(S) * [v(S union {i}) - v(S)]`

The weighting averages over every possible channel ordering, which gives
Shapley its fairness properties.

### Computational constraint

Exact Shapley evaluation is `O(2^n)`. Adding one channel doubles the number of
coalitions:

| Players | Coalitions |
|---:|---:|
| 6 | 64 |
| 8 | 256 |
| 12 | 4,096 |
| 20 | 1,048,576 |

The implementation therefore defaults to the top eight channels ranked by
converted-path presence. Channels outside the cap receive zero exact-Shapley
credit in that run. For a larger production taxonomy, use channel grouping,
sampling-based Shapley approximation, or hierarchical attribution.

Use Shapley when interaction effects are important, the channel set is small,
and stakeholders need a principled allocation with explicit fairness logic.

Advantages:

- Measures average marginal contribution rather than path position alone.
- Recognizes upper-funnel channels that improve multi-channel coalitions.
- Has a strong mathematical fairness foundation.

Limitations:

- Exponential computational cost.
- Sensitive to how coalition value is estimated.
- Correlated channel exposure can still confound interpretation.
- Observational Shapley values are not experimental causal effects.

## Reading the comparison output

The runner creates:

- `data/processed/attribution_model_comparison_long.csv`
- `data/processed/attribution_model_comparison.csv`
- `data/processed/attribution_model_comparison_by_stage.csv`
- `dashboards/plotly/attribution_money_chart.html`

The current full-data result assigns:

| Model | Bottom funnel | Mid funnel | Upper funnel |
|---|---:|---:|---:|
| Last Touch | 67.2% | 19.8% | 13.0% |
| Markov | 67.0% | 19.8% | 13.2% |
| Shapley | 45.7% | 16.2% | 38.1% |

This is the central analytical lesson. Last Touch reports where conversion was
captured. Shapley reports which channels improved the value of channel
coalitions. Markov sits between those views because it follows the observed
transition graph and uses non-conversions.

ROAS in the output is:

`attributed revenue / observed channel spend`

Spend does not change between models; only revenue credit changes. A channel's
reported ROAS can therefore change materially even though the underlying media
cost is identical.

## Recommended operating practice

- Keep Last Touch for continuity with operational reporting.
- Use Linear and Time Decay as transparent sensitivity checks.
- Use Markov as the primary sequence-aware observational model.
- Use Shapley as an interaction-aware comparison for a capped channel set.
- Review model disagreement rather than hiding it.
- Validate major allocation decisions with randomized holdouts, geo tests, or
  another credible incrementality design.

