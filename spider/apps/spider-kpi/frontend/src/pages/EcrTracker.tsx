import { useEffect, useMemo, useState } from 'react'
import { api, type EcrItem } from '../lib/api'

/**
 * Engineering Change Request (ECR) tracker.
 *
 * Source of truth: ClickUp. An ECR is any ClickUp task whose `Category`
 * custom field is set to `ECR`. Lives under Issue Radar in the sidebar
 * and is owner-gated (Joseph only) until the shape stabilizes.
 *
 * The 2026-04-20 plan: add these ClickUp custom fields to ECR tasks
 *   - Category (dropdown) = ECR
 *   - Impact Areas (multi-select: CX / Operations / Manufacturing / Product Engineering)
 *   - Dev Complete (date)
 *   - Production Ready (date)
 *   - Field Deploy (date)
 *   - CX Talking Points (text — customer-facing framing)
 */

const STAGE_ORDER: string[] = [
  'backlog', 'in_review', 'approved', 'in_progress', 'testing', 'deploying', 'deployed',
]

const STAGE_LABEL: Record<string, string> = {
  backlog: 'Backlog',
  in_review: 'In review',
  approved: 'Approved',
  in_progress: 'In progress',
  testing: 'Testing',
  deploying: 'Deploying',
  deployed: 'Deployed',
  other: 'Other',
}

const STAGE_COLORS: Record<string, string> = {
  backlog: '#6b7280',
  in_review: '#6ea8ff',
  approved: '#8b5cf6',
  in_progress: '#f59e0b',
  testing: '#22d3ee',
  deploying: '#3b82f6',
  deployed: '#22c55e',
  other: '#4b5563',
}

const IMPACT_COLORS: Record<string, string> = {
  'CX': '#22d3ee',
  'Customer Experience': '#22d3ee',
  'Operations': '#f59e0b',
  'Manufacturing': '#8b5cf6',
  'Product Engineering': '#6ea8ff',
}

const IMPACT_FILTERS = ['All', 'CX', 'Operations', 'Manufacturing', 'Product Engineering'] as const

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function daysUntil(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const ms = d.getTime() - now.getTime()
  const days = Math.round(ms / (1000 * 60 * 60 * 24))
  if (days === 0) return 'today'
  return days > 0 ? `in ${days}d` : `${Math.abs(days)}d ago`
}

export function EcrTracker() {
  const [items, setItems] = useState<EcrItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [includeClosed, setIncludeClosed] = useState(false)
  const [impactFilter, setImpactFilter] = useState<typeof IMPACT_FILTERS[number]>('All')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    setError(null)
    api.ecrs(includeClosed, ctrl.signal)
      .then(r => setItems(r.ecrs))
      .catch((e: unknown) => {
        if ((e as { name?: string }).name !== 'AbortError') {
          setError(e instanceof Error ? e.message : String(e))
        }
      })
      .finally(() => setLoading(false))
    return () => ctrl.abort()
  }, [includeClosed])

  const filtered = useMemo(() => {
    if (impactFilter === 'All') return items
    const target = impactFilter === 'CX' ? ['CX', 'Customer Experience'] : [impactFilter]
    return items.filter(e => e.impact_areas.some(a => target.includes(a)))
  }, [items, impactFilter])

  const stageCounts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const e of filtered) out[e.pipeline_stage] = (out[e.pipeline_stage] ?? 0) + 1
    return out
  }, [filtered])

  const impactCounts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const e of items) {
      for (const a of e.impact_areas) out[a] = (out[a] ?? 0) + 1
    }
    return out
  }, [items])

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <h1>Engineering Change Requests</h1>
          <p className="page-subhead">
            Source of truth: ClickUp tasks with <code>Category = ECR</code>. Filter by impact area to see
            what each downstream team should be watching, when it lands in production, and what CX should
            tell customers when they ask.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={includeClosed} onChange={e => setIncludeClosed(e.target.checked)} />
            Include closed
          </label>
        </div>
      </header>

      {/* Pipeline strip */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Pipeline</strong>
          <p className="venom-chart-sub">
            {filtered.length} ECR{filtered.length === 1 ? '' : 's'} visible ({impactFilter === 'All' ? 'all divisions' : impactFilter})
          </p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${STAGE_ORDER.length}, 1fr)`, gap: 6 }}>
          {STAGE_ORDER.map(stage => {
            const n = stageCounts[stage] ?? 0
            const color = STAGE_COLORS[stage]
            return (
              <div key={stage} style={{
                padding: 10, borderRadius: 8, background: 'rgba(255,255,255,0.03)',
                border: `1px solid ${color}44`,
              }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  {STAGE_LABEL[stage]}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color }}>{n}</div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Impact area filter */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Filter by impact area</strong>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {IMPACT_FILTERS.map(f => {
            const on = impactFilter === f
            const n = f === 'All' ? items.length : impactCounts[f] ?? (f === 'CX' ? impactCounts['Customer Experience'] ?? 0 : 0)
            const color = f === 'All' ? '#6ea8ff' : (IMPACT_COLORS[f] ?? '#6ea8ff')
            return (
              <button
                key={f}
                onClick={() => setImpactFilter(f)}
                style={{
                  padding: '6px 12px', borderRadius: 20, cursor: 'pointer',
                  border: `1px solid ${on ? color : 'rgba(255,255,255,0.15)'}`,
                  background: on ? color + '22' : 'transparent',
                  color: on ? '#fff' : 'var(--muted)',
                  fontSize: 12,
                }}
              >
                {f} · {n}
              </button>
            )
          })}
        </div>
      </section>

      {loading ? (
        <section className="card"><div className="state-message">Loading ECRs…</div></section>
      ) : error ? (
        <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
      ) : filtered.length === 0 ? (
        <section className="card">
          <div className="state-message">
            {items.length === 0
              ? 'No ECRs found in ClickUp yet. Tag a task with Category = ECR to see it here.'
              : `No ECRs match the ${impactFilter} filter.`}
          </div>
        </section>
      ) : (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Active ECRs</strong>
            <p className="venom-chart-sub">
              Sorted by Field Deploy target (soonest first). Click a row to expand the description
              and CX talking points.
            </p>
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            {[...filtered].sort((a, b) => {
              const ax = a.field_deploy ? new Date(a.field_deploy).getTime() : Number.MAX_SAFE_INTEGER
              const bx = b.field_deploy ? new Date(b.field_deploy).getTime() : Number.MAX_SAFE_INTEGER
              return ax - bx
            }).map(e => {
              const isOpen = !!expanded[e.task_id]
              const stageColor = STAGE_COLORS[e.pipeline_stage] ?? '#6b7280'
              return (
                <div
                  key={e.task_id}
                  style={{
                    padding: 12, borderRadius: 8,
                    background: 'rgba(255,255,255,0.03)',
                    border: `1px solid ${stageColor}44`,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{
                          padding: '2px 8px', borderRadius: 10,
                          background: stageColor + '33', color: stageColor,
                          fontSize: 10, textTransform: 'uppercase', fontWeight: 600, letterSpacing: 0.5,
                        }}>
                          {STAGE_LABEL[e.pipeline_stage]}
                        </span>
                        {e.custom_id && (
                          <span style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'monospace' }}>
                            {e.custom_id}
                          </span>
                        )}
                        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
                          {e.status ?? '—'}
                        </span>
                      </div>
                      <div style={{ fontWeight: 600, marginTop: 4, fontSize: 14 }}>
                        {e.name ?? '(untitled)'}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                        {e.impact_areas.length === 0 ? (
                          <span style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>
                            No impact areas set
                          </span>
                        ) : e.impact_areas.map(a => (
                          <span key={a} style={{
                            padding: '2px 8px', borderRadius: 10, fontSize: 10,
                            background: (IMPACT_COLORS[a] ?? '#6ea8ff') + '22',
                            color: IMPACT_COLORS[a] ?? '#6ea8ff',
                            border: `1px solid ${(IMPACT_COLORS[a] ?? '#6ea8ff')}44`,
                          }}>{a}</span>
                        ))}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right', fontSize: 11 }}>
                      {e.url && (
                        <a href={e.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11 }}>
                          Open in ClickUp ↗
                        </a>
                      )}
                    </div>
                  </div>

                  {/* Date strip */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 10 }}>
                    {[
                      { label: 'Dev Complete', iso: e.dev_complete },
                      { label: 'Production Ready', iso: e.production_ready },
                      { label: 'Field Deploy', iso: e.field_deploy },
                    ].map(m => (
                      <div key={m.label} style={{ padding: 8, borderRadius: 6, background: 'rgba(255,255,255,0.02)' }}>
                        <div style={{ fontSize: 9, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                          {m.label}
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{fmtDate(m.iso)}</div>
                        <div style={{ fontSize: 10, color: 'var(--muted)' }}>{daysUntil(m.iso)}</div>
                      </div>
                    ))}
                  </div>

                  {/* CX Talking Points — always show a hint, expand for full text */}
                  {e.cx_talking_points && (
                    <div style={{
                      marginTop: 10, padding: 10, borderRadius: 6,
                      background: 'rgba(34,211,238,0.08)', border: '1px solid rgba(34,211,238,0.2)',
                    }}>
                      <div style={{ fontSize: 10, color: '#22d3ee', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>
                        CX talking points
                      </div>
                      <div style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>
                        {isOpen ? e.cx_talking_points : e.cx_talking_points.slice(0, 220)}
                        {!isOpen && e.cx_talking_points.length > 220 ? '…' : ''}
                      </div>
                    </div>
                  )}

                  {(e.description || (e.cx_talking_points && e.cx_talking_points.length > 220)) && (
                    <button
                      onClick={() => setExpanded(prev => ({ ...prev, [e.task_id]: !prev[e.task_id] }))}
                      style={{
                        marginTop: 8, background: 'none', border: 'none',
                        color: 'var(--muted)', fontSize: 11, cursor: 'pointer', padding: 0,
                      }}
                    >
                      {isOpen ? '▾ Hide details' : '▸ Show description + full talking points'}
                    </button>
                  )}

                  {isOpen && e.description && (
                    <div style={{ marginTop: 8, padding: 10, borderRadius: 6, background: 'rgba(255,255,255,0.02)', fontSize: 12, whiteSpace: 'pre-wrap' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>
                        Description
                      </div>
                      {e.description}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
