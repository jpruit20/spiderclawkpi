# Spider Shared Memory

## Durable rules
- One Spider agent with multiple scoped sessions
- KPI dashboard work is the primary active initiative
- Durable facts go in `MEMORY.md` or `memory/topics/`
- Session continuity goes in `memory/sessions/`
- Sidecar feedback is advisory and must be validated before promotion to durable memory
- Disk files are the only durable memory for this workspace
- Prefer compact checkpoint summaries over long transcript carry-forward
- Stable design intent belongs in topic memory, not transient session chatter
- For major KPI dashboard/frontend/backend updates, done means commit, push, and deploy/verify production rather than leaving changes local-only
- External voice-of-customer monitoring should be kept distinct from internal support operations
- Use APIs, approved exports, or compliant connectors where possible instead of brittle blind scraping

## Cross-topic operating decisions
- 2026-04-03 - KPI dashboard optimization standard adopted - prioritize meaningful, actionable, decision-grade representation over decorative analytics
- 2026-04-03 - Memory boundary rule reinforced - stable company truth, topic truth, and active session execution must remain separated
- 2026-04-03 - Source-of-truth discipline required - important metrics must map to an explicit system of record or be labeled as approximate
- 2026-04-03 - Voice-of-customer expansion approved - KPI dashboard should integrate external public discussion signals into the Support / CX layer with clear labeling

## Shared domains
- KPI dashboard
- UX/UI and conversion optimization
- supply chain
- app / analytics / instrumentation
- product / firmware
- marketing
- support / CX intelligence

## Open items
- Keep topic memory concise as the dashboard matures
- Promote only validated KPI definitions and data-source rules into topic memory
- Confirm final connector set and source precedence as integrations are implemented
