# KPI Dashboard - Validated Rules & Definitions

## Marketing Page Patterns

### UX Friction Insights (Clarity)
- **Business impact ranking**: Sort by `friction_score × sessions` to prioritize high-traffic, high-friction pages
- **Top 3 focus**: Only show the 3 most impactful pages instead of overwhelming detail
- **Dominant issue identification**: Categorize whether main problem is rage clicks, dead clicks, script errors, or quick backs
- **Severity badges**: Critical (>50 friction), High (25-50), Medium (<25)
- **Actionable recommendations**: Each insight tells exactly what to fix

### KPI Strip Cards
- Show 7-day or 30-day sparklines for trajectory visibility
- Include week-over-week delta indicators where available
- Display trend direction arrows with percentage changes

### Funnel Visualization
- Show drop-off percentages between stages
- Highlight "Biggest Leak" with visual badge when step underperforms vs benchmarks
- Flag when checkout→purchase drop-off exceeds 50%

## General Dashboard Principles

### Truth State Model
- All KPIs must carry explicit `truth_state` labels
- Actions must have `confidence` and `scope` attributes
- Sample-limited metrics must be labeled as "directional only"

### Action Prioritization
- Rank by business impact (revenue × confidence)
- Suppress low-sample actions from top-rank while preserving as early warning
- Include severity, recommended action, and evidence sources

### Source Health
- All connectors must report health status
- Stale data must show age indicators
- Missing sources must block dependent metrics explicitly
