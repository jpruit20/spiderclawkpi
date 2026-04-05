import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { MetricProvenancePanel, MetricProvenanceItem } from '../components/MetricProvenancePanel'
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

  const actionItems = useMemo(() => [
    sourceReady ? 'Clarity and GA4 are live; prioritize high-friction journeys, rage/dead clicks, scroll abandonment, and checkout drop-off before cosmetic page tweaks.' : 'Finish connector configuration for Clarity and GA4 so behavior insights become decision-grade instead of anecdotal.',
    'Use this page to decide what UX issue to fix next, not to browse heatmaps endlessly. Focus on friction tied to revenue, checkout completion, and support burden.',
    'Translate session behavior into a single next action per pattern: fix a page, fix a funnel step, fix a message, or stop investigating.',
  ], [sourceReady])

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

      <ActionBlock title="Recommended UX Actions" items={actionItems} />
      <MetricProvenancePanel title="Behavior Data Provenance" items={provenanceItems} />

      {loading ? <Card title="Behavior Status"><div className="state-message">Loading UX data-source readiness…</div></Card> : null}
      {error ? <Card title="Behavior Error"><div className="state-message error">{error}</div></Card> : null}

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
