# KPI Dashboard — Validated Patterns

## Marketing Page Standards

### KPI Strip Cards
- Each KPI card displays: label, value, sub (prior comparison), truth badge, delta badge
- **Sparklines**: 7-day trend visualization from last 7 daily data points
  - Green line: value trending up (last > first)
  - Red line: value trending down (last < first)
  - Displayed inline with value for at-a-glance trajectory

### Funnel Visualization
- Sessions → PDP → Add to Cart → Checkout → Purchase
- Drop-off percentages shown between stages
- **Leak Severity Badges**:
  - Critical (red): >50% drop-off
  - High (orange): 25-50% drop-off
  - Medium (neutral): <25% drop-off
- **Biggest Leak Banner**: Highlights the step with highest drop-off for immediate optimization focus
- Biggest leak step gets background highlight + dedicated badge

### UX Friction Insights
- AI-prioritized ranking: `friction_score × sessions` for business impact
- Top 3 most impactful pages displayed (not verbose raw data)
- Severity badges: Critical (>50 friction), High (25-50), Medium (<25)
- Dominant issue identification: rage clicks, dead clicks, script errors, or quick backs
- Clear action recommendations per insight

## Truth State Labels
- `canonical`: Verified from authoritative source (e.g., Shopify orders)
- `proxy`: Derived/estimated from secondary signals
- `estimated`: Modeled values (e.g., funnel stages 2-4)
- `degraded`: Source temporarily unreliable
- `blocked`: Required data source unavailable

## Action Prioritization
- Actions sorted by business impact score
- Critical actions surface when metrics decline vs prior period
- Blocked states clearly explain: decision blocked, missing source, still trustworthy data, required action to unblock
