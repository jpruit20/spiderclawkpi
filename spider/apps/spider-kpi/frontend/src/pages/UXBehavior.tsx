import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { MetricProvenancePanel, MetricProvenanceItem } from '../components/MetricProvenancePanel'
import { StatePanel } from '../components/StatePanel'
import { api, ApiError, getApiBase } from '../lib/api'
import { SourceHealthItem } from '../lib/types'

function sourceByName(rows: SourceHealthItem[], name: string) {
  return rows.find((row) => row.source === name) || null
}

export function UXBehavior() {
  const [rows, setRows] = useState<SourceHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.sourceHealth()
        if (!cancelled) setRows(payload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load UX behavior sources')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const clarity = sourceByName(rows, 'clarity')
  const ga4 = sourceByName(rows, 'ga4')
  const sourceReady = [clarity, ga4].filter(Boolean).every((row) => row?.derived_status === 'healthy')
  const telemetryHealthyCount = [clarity, ga4].filter((row) => row?.derived_status === 'healthy').length
  const telemetryLag = Math.max(clarity?.stale_minutes || 0, ga4?.stale_minutes || 0)

  const actionItems = useMemo(() => [
    sourceReady ? 'Clarity and GA4 are live; prioritize high-friction journeys, rage/dead clicks, scroll abandonment, and checkout drop-off before cosmetic page tweaks.' : 'Finish connector configuration for Clarity and GA4 so behavior insights become decision-grade instead of anecdotal.',
    'Use this page to decide what UX issue to fix next, not to browse heatmaps endlessly. Focus on friction tied to revenue, checkout completion, and support burden.',
    'Translate session behavior into a single next action per pattern: fix a page, fix a funnel step, fix a message, or stop investigating.',
  ], [sourceReady])

  const canonicalEventRows = useMemo(() => [
    { event: 'view_product', owner: 'GA4 + Clarity + app telemetry', intent: 'Baseline PDP exposure and product-interest context' },
    { event: 'add_to_cart', owner: 'GA4 + Clarity + app telemetry', intent: 'Track merchandising and PDP persuasion' },
    { event: 'begin_checkout', owner: 'GA4 + Clarity + app telemetry', intent: 'Detect cart-to-checkout leakage' },
    { event: 'add_payment_info', owner: 'GA4 + Clarity + app telemetry', intent: 'Identify payment-step hesitation and field friction' },
    { event: 'select_shipping_method', owner: 'GA4 + Clarity + app telemetry', intent: 'Expose shipping-cost or timing friction during checkout' },
    { event: 'purchase', owner: 'GA4 + Clarity + app telemetry', intent: 'Anchor the successful end-state for funnel and UX attribution' },
  ], [])

  const readinessChecks = useMemo(() => ([
    { label: 'GA4 connector healthy', ready: ga4?.derived_status === 'healthy', detail: ga4?.status_summary || 'Missing from source health' },
    { label: 'Clarity connector healthy', ready: clarity?.derived_status === 'healthy', detail: clarity?.status_summary || 'Missing from source health' },
    { label: 'Canonical event set defined', ready: true, detail: 'Scaffolded in UI; still needs backend/shared telemetry policy promotion' },
    { label: 'Decision rules documented', ready: true, detail: 'Page now frames telemetry as action-ranking input instead of dashboard theater' },
  ]), [clarity, ga4])

  const readinessScore = readinessChecks.filter((item) => item.ready).length

  const provenanceItems: MetricProvenanceItem[] = [
    {
      metric: 'Behavior Friction Signals',
      sourceSystem: 'Microsoft Clarity',
      queryLogic: 'planned export-data API summaries for rage clicks, dead clicks, JS errors, scroll depth, and page-level friction',
      timeWindow: 'short rolling window (e.g. 3-7 days)',
      refreshCadence: 'poll sync',
      transformationLogic: 'aggregate high-signal UX behaviors into decision-ready summaries',
      caveats: 'Should summarize only a few high-signal patterns; avoid raw session-noise surfaces in the main dashboard.',
    },
    {
      metric: 'Traffic / Funnel Context',
      sourceSystem: 'GA4',
      queryLogic: 'runReport by date/page/event for sessions, users, pageviews, bounce, purchase revenue',
      timeWindow: 'rolling window + compare mode',
      refreshCadence: 'poll sync',
      transformationLogic: 'context layer for whether UX friction is happening on meaningful traffic and revenue pathways',
      caveats: 'Should be used to prioritize UX interventions, not duplicate broad marketing reporting.',
    },
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Website UX / Behavior</h2>
        <p>Decision-grade UX intelligence for Spider Grills: identify friction, prioritize fixes, and turn behavior patterns into operational actions.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>

      {!loading && !error ? (
        <div className="three-col">
          <Card title="Telemetry Ready"><div className="hero-metric">{telemetryHealthyCount}/2</div><div className="state-message">GA4 + Clarity connectors healthy right now</div></Card>
          <Card title="Readiness Score"><div className="hero-metric">{readinessScore}/{readinessChecks.length}</div><div className="state-message">Checks currently passing before UX decisions are trusted</div></Card>
          <Card title="Worst Lag"><div className="hero-metric">{telemetryLag || 0}m</div><div className="state-message">Oldest telemetry freshness lag</div></Card>
        </div>
      ) : null}

      <ActionBlock title="Recommended UX Actions" items={actionItems} />
      <MetricProvenancePanel title="Behavior Data Provenance" items={provenanceItems} />

      {loading ? <Card title="Behavior Status"><div className="state-message">Loading UX data-source readiness…</div></Card> : null}
      {error ? <Card title="Behavior Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <div className="three-col">
          <Card title="Decision State">
            {sourceReady ? (
              <StatePanel kind="ready" tone="good" message="Telemetry is healthy enough to prioritize UX fixes using both behavioral evidence and funnel context." />
            ) : (
              <StatePanel kind="partial" tone="warn" message="Telemetry is not fully healthy yet. Use this page to close instrumentation and feed gaps before treating UX patterns as decision-grade." />
            )}
          </Card>
          <Card title="Normalization State">
            {sourceReady ? (
              <StatePanel kind="ready" tone="good" message="Behavior telemetry is normalized enough to rank UX work instead of debating data trust." detail="Next maturity step is shared backend policy, not more frontend chrome." />
            ) : (
              <StatePanel kind="partial" tone="warn" message="Normalization is still partial because at least one behavior connector is not healthy." detail="Keep instrumentation debt explicit instead of masking it with empty charts." />
            )}
          </Card>
          <Card title="Next Maturity Step">
            <div className="stack-list compact">
              <div className="list-item">
                <strong>Move from readiness to prioritization</strong>
                <small>Use friction + meaningful traffic + revenue pathway impact as the ranking rule for UX work.</small>
              </div>
            </div>
          </Card>
        </div>
      ) : null}

      {!loading && !error ? (
        <div className="two-col two-col-equal">
          <Card title="Clarity Readiness">
            <div className="stack-list">
              <div className={`list-item ${clarity?.derived_status === 'healthy' ? 'status-good' : 'status-warn'}`}>
                <strong>Clarity connector</strong>
                <p>{clarity?.status_summary || 'Not present in source health yet.'}</p>
                <small>Status: {clarity?.derived_status || 'missing'} · Sync mode: {clarity?.sync_mode || 'n/a'}</small>
              </div>
              <div className="list-item">
                <strong>Planned signals</strong>
                <small>Rage clicks · Dead clicks · Scroll abandonment · Page frustration clusters · Session error burden</small>
              </div>
            </div>
          </Card>

          <Card title="GA4 Readiness">
            <div className="stack-list">
              <div className={`list-item ${ga4?.derived_status === 'healthy' ? 'status-good' : 'status-warn'}`}>
                <strong>GA4 connector</strong>
                <p>{ga4?.status_summary || 'Not present in source health yet.'}</p>
                <small>Status: {ga4?.derived_status || 'missing'} · Sync mode: {ga4?.sync_mode || 'n/a'}</small>
              </div>
              <div className="list-item">
                <strong>Planned context layer</strong>
                <small>Sessions · Users · Pageviews · Bounce · Revenue context for UX friction prioritization</small>
              </div>
            </div>
          </Card>
        </div>
      ) : null}

      <div className="two-col two-col-equal">
        <Card title="Telemetry Readiness Score">
          <div className="hero-metric">{readinessScore}/{readinessChecks.length}</div>
          <div className="state-message">Decision-readiness checks currently passing</div>
        </Card>
        <Card title="Telemetry Freshness Risk">
          <div className="hero-metric">{telemetryLag || 0}m</div>
          <div className="state-message">Worst connector lag that could distort current UX interpretation</div>
        </Card>
      </div>

      <div className="two-col two-col-equal">
        <Card title="Venom / Telemetry Layer">
          <div className="stack-list">
            <div className="list-item">
              <strong>Decision question</strong>
              <p>Can we trust the behavioral evidence enough to change page UX, checkout flow, or messaging this week?</p>
            </div>
            <div className="list-item">
              <strong>Telemetry required</strong>
              <small>GA4 sessions + funnel events · Clarity rage/dead clicks · JS error burden · landing page friction by template</small>
            </div>
            <div className="list-item">
              <strong>Instrumentation debt</strong>
              <small>Still missing a canonical cross-tool event set for PDP view, add-to-cart, checkout start, payment attempt, shipping-method friction, and purchase completion.</small>
            </div>
          </div>
        </Card>
        <Card title="Normalized UX state model">
          {sourceReady ? (
            <StatePanel kind="ready" tone="good" message="Behavior telemetry appears healthy. Next step is prioritization, not connector debugging." detail="Use rising friction + meaningful traffic + revenue pathway impact as the ranking rule." />
          ) : (
            <StatePanel kind="partial" tone="warn" message="This page is intentionally honest about partial telemetry. No faux heatmap confidence until both behavior and funnel context are healthy." detail="If a connector fails, keep this page in partial state instead of silently showing empty charts." />
          )}
        </Card>
      </div>

      <div className="two-col two-col-equal">
        <Card title="Canonical Event Contract">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Owner</th>
                  <th>Decision intent</th>
                </tr>
              </thead>
              <tbody>
                {canonicalEventRows.map((row) => (
                  <tr key={row.event}>
                    <td>{row.event}</td>
                    <td>{row.owner}</td>
                    <td>{row.intent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Telemetry Maturity Checklist">
          <div className="stack-list">
            {readinessChecks.map((item) => (
              <div className={`list-item ${item.ready ? 'status-good' : 'status-warn'}`} key={item.label}>
                <div className="item-head">
                  <strong>{item.label}</strong>
                  <span className={`badge ${item.ready ? 'badge-good' : 'badge-warn'}`}>{item.ready ? 'ready' : 'pending'}</span>
                </div>
                <small>{item.detail}</small>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="How this page should be used">
        <div className="stack-list">
          <div className="list-item">
            <strong>What changed?</strong>
            <p>Which pages or funnel steps are showing newly elevated friction on meaningful traffic or revenue pathways?</p>
          </div>
          <div className="list-item">
            <strong>Why did it change?</strong>
            <p>Correlate Clarity friction signals with recent launches, pricing changes, site changes, or traffic quality shifts.</p>
          </div>
          <div className="list-item">
            <strong>What to do next?</strong>
            <p>Prioritize one UX fix at a time: content/message fix, page layout fix, funnel-step fix, or instrumentation fix.</p>
          </div>
        </div>
      </Card>
    </div>
  )
}
