import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../lib/api'
import type {
  SharepointAnalysisStatusResponse,
  SharepointCogsResponse,
  SharepointDocSummary,
  SharepointFileAnalysisRow,
  SharepointFileAnalysesResponse,
  SharepointHeadlineMetric,
  SharepointProductNarrative,
} from '../lib/api'

/**
 * Visual SharePoint intelligence card.
 *
 * Layout (top → bottom):
 *   1. Product tabs
 *   2. Headline metric tiles (3-6, color-toned)
 *   3. COGS hero with breakdown donut
 *   4. Vendor concentration bar chart
 *   5. Active workstreams as severity chips
 *   6. Data quality alert banners
 *   7. Revision/event timeline
 *   8. Narrative (collapsed, expandable)
 *   9. File drill-down (separate tab)
 *
 * The dashboard reads quickly: headline numbers + charts answer the
 * "what's the COGS, what's broken, who supplies us" questions in
 * seconds. The narrative is there for the long-form reader.
 */

const PRODUCTS = ['Huntsman', 'Giant Huntsman', 'Venom', 'Webcraft', 'Giant Webcraft'] as const
type Product = (typeof PRODUCTS)[number]

interface Props {
  division: 'pe' | 'operations' | 'manufacturing'
  defaultProduct?: Product
}

const TONE_COLORS: Record<string, { fg: string; bg: string; bd: string }> = {
  good: { fg: 'var(--green)', bg: 'rgba(46, 204, 113, 0.08)', bd: 'var(--green)' },
  warn: { fg: 'var(--orange)', bg: 'rgba(243, 156, 18, 0.08)', bd: 'var(--orange)' },
  bad: { fg: 'var(--red)', bg: 'rgba(231, 76, 60, 0.10)', bd: 'var(--red)' },
  neutral: { fg: 'var(--blue)', bg: 'rgba(110, 168, 255, 0.06)', bd: 'var(--blue)' },
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'var(--red)',
  warn: 'var(--orange)',
  info: 'var(--blue)',
}

// Recharts pie palette
const PIE_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#84cc16', '#ec4899', '#f97316', '#14b8a6', '#a855f7', '#64748b',
]

function fmtUSD(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function relativeAge(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  const d = Math.floor(ms / 86400000)
  if (d < 1) return 'today'
  if (d < 7) return `${d}d ago`
  if (d < 60) return `${Math.floor(d / 7)}w ago`
  if (d < 365) return `${Math.floor(d / 30)}mo ago`
  return `${(d / 365).toFixed(1)}y ago`
}

function MetricTile({
  metric,
  citationDocs,
}: {
  metric: SharepointHeadlineMetric
  citationDocs: Record<string, SharepointDocSummary>
}) {
  const tc = TONE_COLORS[metric.tone] ?? TONE_COLORS.neutral
  const doc = metric.source_document_id ? citationDocs[String(metric.source_document_id)] : null
  return (
    <div
      style={{
        padding: 12,
        background: tc.bg,
        borderLeft: `3px solid ${tc.bd}`,
        borderRadius: 4,
        minHeight: 76,
      }}
      title={doc ? `Source: ${doc.name}` : undefined}
    >
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>
        {metric.label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tc.fg, lineHeight: 1.1, marginTop: 4 }}>
        {metric.value}
      </div>
      {metric.unit && (
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>
          {metric.unit}
          {doc && (
            <a
              href={doc.web_url ?? '#'}
              target="_blank"
              rel="noreferrer"
              style={{ marginLeft: 6, color: 'var(--blue)', textDecoration: 'none' }}
              title={doc.path}
            >
              📄
            </a>
          )}
        </div>
      )}
    </div>
  )
}

function CogsHero({
  cogs,
  citationDocs,
}: {
  cogs: NonNullable<SharepointProductNarrative['cogs_summary']>
  citationDocs: Record<string, SharepointDocSummary>
}) {
  const sourceDoc = cogs.canonical_document_id ? citationDocs[String(cogs.canonical_document_id)] : null
  const breakdown = cogs.breakdown ?? []
  const confidenceColor =
    cogs.confidence === 'high' ? 'var(--green)' :
    cogs.confidence === 'medium' ? 'var(--orange)' : 'var(--red)'

  // Build pie data
  const pieData = breakdown.map((b, i) => ({
    name: b.category,
    value: b.cost_usd,
    color: PIE_COLORS[i % PIE_COLORS.length],
    sourceDocId: b.source_document_id,
    notes: b.notes,
  }))

  return (
    <div
      style={{
        padding: 14,
        background: 'var(--panel-2)',
        borderRadius: 6,
        borderLeft: `4px solid ${confidenceColor}`,
        marginTop: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
        {/* Hero number block */}
        <div style={{ flex: '0 0 220px' }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>
            COGS per unit
          </div>
          <div style={{ fontSize: 32, fontWeight: 700, lineHeight: 1.05, marginTop: 4 }}>
            {fmtUSD(cogs.canonical_total_usd)}
          </div>
          {(cogs.coated_total_usd != null || cogs.uncoated_total_usd != null) && (
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              {cogs.uncoated_total_usd != null && <>uncoated <strong>{fmtUSD(cogs.uncoated_total_usd)}</strong></>}
              {cogs.uncoated_total_usd != null && cogs.coated_total_usd != null && ' · '}
              {cogs.coated_total_usd != null && <>coated <strong>{fmtUSD(cogs.coated_total_usd)}</strong></>}
            </div>
          )}
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 0.5,
                padding: '2px 6px',
                borderRadius: 3,
                background: confidenceColor,
                color: '#fff',
                textTransform: 'uppercase',
              }}
            >
              {cogs.confidence} confidence
            </span>
            {cogs.canonical_line_count != null && (
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>{cogs.canonical_line_count} lines</span>
            )}
          </div>
          {sourceDoc && (
            <div style={{ marginTop: 8 }}>
              <a
                href={sourceDoc.web_url ?? '#'}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: 11, color: 'var(--blue)', textDecoration: 'none' }}
                title={sourceDoc.path}
              >
                📄 {sourceDoc.name.length > 50 ? sourceDoc.name.slice(0, 50) + '…' : sourceDoc.name}
              </a>
            </div>
          )}
          {cogs.notes && (
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.5 }}>
              {cogs.notes}
            </div>
          )}
        </div>

        {/* Breakdown donut + legend */}
        {breakdown.length > 0 && (
          <div style={{ flex: 1, minWidth: 280, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ width: 200, height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={50}
                    outerRadius={88}
                    paddingAngle={1}
                  >
                    {pieData.map((d, i) => <Cell key={i} fill={d.color} stroke="var(--panel)" strokeWidth={1} />)}
                  </Pie>
                  <Tooltip
                    formatter={(v: number, _n: string, p: any) => [fmtUSD(v), p.payload.name]}
                    contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ flex: 1, fontSize: 11 }}>
              <div style={{ color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 6, fontSize: 10 }}>
                Breakdown
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {pieData.map((d, i) => {
                  const doc = d.sourceDocId ? citationDocs[String(d.sourceDocId)] : null
                  const totalSafe = (cogs.canonical_total_usd ?? 0) || pieData.reduce((s, x) => s + x.value, 0) || 1
                  const pct = (d.value / totalSafe) * 100
                  return (
                    <div key={i} style={{ display: 'grid', gridTemplateColumns: '12px 1fr auto auto', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ width: 10, height: 10, background: d.color, borderRadius: 2, display: 'inline-block' }} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={d.notes ?? d.name}>
                        {d.name}
                        {doc && <a href={doc.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', marginLeft: 4, textDecoration: 'none' }}>📄</a>}
                      </span>
                      <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>{pct.toFixed(0)}%</span>
                      <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{fmtUSD(d.value)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function VendorChart({
  vendors,
  citationDocs,
}: {
  vendors: Array<{ name: string; mentions: number; documents_seen: number; role: string | null; estimated_spend_usd?: number | null }>
  citationDocs: Record<string, SharepointDocSummary>
}) {
  // Use estimated_spend if available, else mentions count
  const data = vendors.slice(0, 10).map((v, i) => ({
    name: v.name.length > 28 ? v.name.slice(0, 28) + '…' : v.name,
    fullName: v.name,
    role: v.role,
    spend: v.estimated_spend_usd ?? null,
    docs: v.documents_seen,
    color: PIE_COLORS[i % PIE_COLORS.length],
  }))
  const haveSpend = data.some(d => d.spend != null)

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 6 }}>
        Vendor concentration · top {data.length}
      </div>
      <div style={{ height: Math.max(180, data.length * 28) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 60, left: 8, bottom: 4 }}>
            <XAxis
              type="number"
              tick={{ fontSize: 10, fill: 'var(--muted)' }}
              tickFormatter={v => haveSpend ? `$${(v / 1000).toFixed(0)}k` : String(v)}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 10, fill: 'var(--text)' }}
              width={140}
            />
            <Tooltip
              formatter={(v: number) => haveSpend ? fmtUSD(v) : `${v} files`}
              labelFormatter={(_, payload: any) => {
                const p = payload?.[0]?.payload
                return p?.fullName + (p?.role ? ` · ${p.role}` : '')
              }}
              contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
            />
            <Bar dataKey={haveSpend ? 'spend' : 'docs'} radius={[0, 4, 4, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function WorkstreamChips({ workstreams }: { workstreams: string[] }) {
  if (!workstreams.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 6 }}>
        Active workstreams
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {workstreams.map((w, i) => (
          <span
            key={i}
            style={{
              padding: '5px 10px',
              borderRadius: 4,
              background: 'var(--panel-2)',
              borderLeft: '3px solid var(--blue)',
              fontSize: 11.5,
              fontWeight: 500,
            }}
          >
            🔧 {w}
          </span>
        ))}
      </div>
    </div>
  )
}

function DataQualityAlerts({
  issues,
  citationDocs,
}: {
  issues: NonNullable<SharepointProductNarrative['data_quality_issues']>
  citationDocs: Record<string, SharepointDocSummary>
}) {
  if (!issues.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 6 }}>
        Data quality alerts ({issues.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {issues.map((iss, i) => (
          <div
            key={i}
            style={{
              padding: '8px 10px',
              background: 'var(--panel-2)',
              borderLeft: `3px solid ${SEVERITY_COLOR[iss.severity] || 'var(--muted)'}`,
              borderRadius: 4,
              fontSize: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  padding: '1px 5px',
                  borderRadius: 3,
                  background: SEVERITY_COLOR[iss.severity] || 'var(--muted)',
                  color: '#fff',
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                }}
              >
                {iss.severity}
              </span>
              <span style={{ flex: 1 }}>{iss.issue}</span>
            </div>
            {iss.suggested_fix && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, paddingLeft: 4 }}>
                <strong>Fix:</strong> {iss.suggested_fix}
              </div>
            )}
            {iss.affected_document_ids && iss.affected_document_ids.length > 0 && (
              <div style={{ marginTop: 4, paddingLeft: 4 }}>
                {iss.affected_document_ids.map(id => {
                  const d = citationDocs[String(id)]
                  return d ? (
                    <a key={id} href={d.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ marginRight: 8, color: 'var(--blue)', fontSize: 10, textDecoration: 'none' }}>
                      📄 {d.name.length > 35 ? d.name.slice(0, 35) + '…' : d.name}
                    </a>
                  ) : <span key={id} style={{ marginRight: 6, fontSize: 10, color: 'var(--muted)' }}>doc:{id}</span>
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function Timeline({
  events,
  citationDocs,
}: {
  events: NonNullable<SharepointProductNarrative['timeline']>
  citationDocs: Record<string, SharepointDocSummary>
}) {
  if (!events.length) return null
  // Sort newest first
  const sorted = [...events].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  const KIND_ICON: Record<string, string> = {
    revision: '🔄',
    decision: '✅',
    shipment: '🚢',
    qc_event: '🔍',
    quote: '💬',
    invoice: '💵',
    other: '•',
  }
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 6 }}>
        Timeline ({events.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 280, overflowY: 'auto' }}>
        {sorted.map((e, i) => {
          const doc = e.document_id ? citationDocs[String(e.document_id)] : null
          return (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '90px 24px 1fr',
                gap: 8,
                padding: '4px 6px',
                fontSize: 12,
                borderBottom: '1px solid rgba(255,255,255,0.03)',
              }}
            >
              <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums', fontSize: 11 }}>{e.date || '—'}</span>
              <span title={e.kind}>{KIND_ICON[e.kind] || '•'}</span>
              <span>
                {e.label}
                {doc && (
                  <a href={doc.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ marginLeft: 6, color: 'var(--blue)', textDecoration: 'none', fontSize: 10 }}>
                    📄
                  </a>
                )}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Render markdown narrative with [doc:N] inline citations replaced by
 *  superscript links to the source file. */
function NarrativeMarkdown({
  text,
  citationDocs,
}: {
  text: string
  citationDocs: Record<string, SharepointDocSummary>
}) {
  const blocks = useMemo(() => text.split(/\n\n+/), [text])
  function renderInline(s: string, keyPrefix: string): JSX.Element[] {
    const out: JSX.Element[] = []
    const re = /(\[doc:(\d+)\]|\*\*([^*]+)\*\*|`([^`]+)`)/g
    let last = 0
    let m: RegExpExecArray | null
    let i = 0
    while ((m = re.exec(s)) !== null) {
      if (m.index > last) out.push(<span key={`${keyPrefix}-${i++}`}>{s.slice(last, m.index)}</span>)
      if (m[2]) {
        const id = m[2]
        const doc = citationDocs[id]
        out.push(
          <a key={`${keyPrefix}-${i++}`} href={doc?.web_url ?? '#'} target="_blank" rel="noreferrer" title={doc ? `${doc.name}` : `doc ${id}`} style={{ color: 'var(--blue)', textDecoration: 'none', fontSize: '0.85em', verticalAlign: 'super', lineHeight: 1, padding: '0 2px' }}>
            [{id}]
          </a>,
        )
      } else if (m[3]) {
        out.push(<strong key={`${keyPrefix}-${i++}`}>{m[3]}</strong>)
      } else if (m[4]) {
        out.push(<code key={`${keyPrefix}-${i++}`} style={{ background: 'var(--panel-2)', padding: '1px 4px', borderRadius: 3, fontSize: '0.9em' }}>{m[4]}</code>)
      }
      last = m.index + m[0].length
    }
    if (last < s.length) out.push(<span key={`${keyPrefix}-${i++}`}>{s.slice(last)}</span>)
    return out
  }
  return (
    <div style={{ lineHeight: 1.6, fontSize: 12.5, color: 'var(--text)' }}>
      {blocks.map((block, bi) => {
        const trimmed = block.trim()
        if (!trimmed) return null
        if (trimmed.startsWith('## ')) {
          return <h4 key={bi} style={{ fontSize: 13, marginTop: 12, marginBottom: 4, color: 'var(--text)' }}>{renderInline(trimmed.slice(3), `h-${bi}`)}</h4>
        }
        if (trimmed.startsWith('# ')) {
          return <h3 key={bi} style={{ fontSize: 14, marginTop: 12, marginBottom: 4, color: 'var(--text)' }}>{renderInline(trimmed.slice(2), `h-${bi}`)}</h3>
        }
        if (trimmed.split('\n').every(l => /^\s*[-*]\s/.test(l))) {
          return (
            <ul key={bi} style={{ paddingLeft: 18, margin: '4px 0' }}>
              {trimmed.split('\n').map((l, li) => <li key={li} style={{ marginBottom: 2 }}>{renderInline(l.replace(/^\s*[-*]\s/, ''), `bul-${bi}-${li}`)}</li>)}
            </ul>
          )
        }
        return <p key={bi} style={{ margin: '6px 0' }}>{renderInline(trimmed.replace(/\n/g, ' '), `p-${bi}`)}</p>
      })}
    </div>
  )
}

export function SharepointIntelligenceCard({ division, defaultProduct }: Props) {
  const [product, setProduct] = useState<Product>(defaultProduct ?? 'Huntsman')
  const [narrative, setNarrative] = useState<SharepointProductNarrative | null>(null)
  const [cogs, setCogs] = useState<SharepointCogsResponse | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<SharepointAnalysisStatusResponse | null>(null)
  const [files, setFiles] = useState<SharepointFileAnalysesResponse | null>(null)
  const [tab, setTab] = useState<'dashboard' | 'narrative' | 'files'>('dashboard')
  const [showOverridePicker, setShowOverridePicker] = useState(false)
  const [overrideError, setOverrideError] = useState<string | null>(null)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [revisionsForOverride, setRevisionsForOverride] = useState<SharepointDocSummary[]>([])

  useEffect(() => {
    const ctl = new AbortController()
    Promise.all([
      api.sharepointProductNarrative(product, ctl.signal).then(setNarrative).catch(() => setNarrative(null)),
      api.sharepointCogs({ spider_product: product }, ctl.signal).then(setCogs).catch(() => setCogs(null)),
      api.sharepointAnalysisStatus(ctl.signal).then(setAnalysisStatus).catch(() => setAnalysisStatus(null)),
      api.sharepointFileAnalyses({ spider_product: product }, ctl.signal).then(setFiles).catch(() => setFiles(null)),
    ]).catch(() => undefined)
    return () => ctl.abort()
  }, [product, division])

  useEffect(() => {
    if (!showOverridePicker) return
    const ctl = new AbortController()
    api.sharepointRevisions(product, 'bom', ctl.signal)
      .then(rev => setRevisionsForOverride(rev.by_assembly.flatMap(b => b.revisions)))
      .catch(() => setRevisionsForOverride([]))
    return () => ctl.abort()
  }, [showOverridePicker, product])

  async function pinSource(docId: number | null) {
    setOverrideSaving(true)
    setOverrideError(null)
    try {
      await api.sharepointSetCanonical({ data_type: 'cogs', spider_product: product, dashboard_division: null, document_id: docId, note: null })
      const fresh = await api.sharepointCogs({ spider_product: product })
      setCogs(fresh)
      setShowOverridePicker(false)
    } catch (err) {
      setOverrideError(err instanceof Error ? err.message : 'Failed to set override (check auth)')
    } finally {
      setOverrideSaving(false)
    }
  }

  const citationDocsObj: Record<string, SharepointDocSummary> = useMemo(() => {
    const out: Record<string, SharepointDocSummary> = {}
    if (narrative?.citation_docs) {
      for (const [k, v] of Object.entries(narrative.citation_docs)) out[k] = v as SharepointDocSummary
    }
    return out
  }, [narrative])

  const isAnalyzing = !narrative?.available && analysisStatus && analysisStatus.files_with_analysis < 5

  return (
    <section className="card">
      {/* Header + product tabs */}
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>SharePoint intelligence — {product}</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Cross-file AI analysis · click any 📄 to open the source
          </div>
        </div>
        {analysisStatus && (
          <span
            title={`Last analysis: ${analysisStatus.last_analysis_at ?? '—'}\nLast synthesis: ${analysisStatus.last_synthesis_at ?? '—'}`}
            style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'var(--panel-2)', color: 'var(--muted)', fontWeight: 600, letterSpacing: 0.4 }}
          >
            {fmtInt(analysisStatus.files_with_analysis)} files analyzed · {analysisStatus.products_with_synthesis} products synthesized
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 10 }}>
        {PRODUCTS.map(p => (
          <button
            key={p}
            onClick={() => setProduct(p)}
            style={{
              padding: '4px 10px',
              borderRadius: 6,
              border: '1px solid rgba(255,255,255,0.1)',
              background: product === p ? 'var(--blue)' : 'var(--panel-2)',
              color: product === p ? '#fff' : 'var(--muted)',
              fontSize: 11,
              fontWeight: product === p ? 600 : 400,
              cursor: 'pointer',
            }}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Section tabs */}
      <div style={{ display: 'flex', gap: 16, marginTop: 12, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        {(['dashboard', 'narrative', 'files'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'none',
              border: 'none',
              padding: '6px 0',
              borderBottom: tab === t ? '2px solid var(--blue)' : '2px solid transparent',
              color: tab === t ? 'var(--text)' : 'var(--muted)',
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: 0.3,
              cursor: 'pointer',
              textTransform: 'uppercase',
            }}
          >
            {t === 'dashboard' ? 'Dashboard' : t === 'narrative' ? 'Narrative' : `Files (${files?.files.length ?? 0})`}
          </button>
        ))}
      </div>

      {/* DASHBOARD (visual) */}
      {tab === 'dashboard' && (
        <div style={{ marginTop: 12 }}>
          {narrative?.available ? (
            <>
              {/* Headline metric tiles */}
              {narrative.headline_metrics && narrative.headline_metrics.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 8 }}>
                  {narrative.headline_metrics.map((m, i) => (
                    <MetricTile key={i} metric={m} citationDocs={citationDocsObj} />
                  ))}
                </div>
              )}

              {/* COGS hero with breakdown donut */}
              {narrative.cogs_summary && narrative.cogs_summary.canonical_total_usd != null && (
                <CogsHero cogs={narrative.cogs_summary} citationDocs={citationDocsObj} />
              )}

              {/* Two-column: vendor chart + workstreams + alerts */}
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(280px, 1fr)', gap: 12, marginTop: 12 }}>
                {/* LEFT: vendors */}
                <div>
                  {narrative.vendor_summary?.top_vendors && narrative.vendor_summary.top_vendors.length > 0 && (
                    <VendorChart vendors={narrative.vendor_summary.top_vendors} citationDocs={citationDocsObj} />
                  )}
                </div>
                {/* RIGHT: workstreams */}
                <div>
                  {narrative.design_status?.active_workstreams && (
                    <WorkstreamChips workstreams={narrative.design_status.active_workstreams} />
                  )}
                </div>
              </div>

              {/* Data quality alerts */}
              {narrative.data_quality_issues && narrative.data_quality_issues.length > 0 && (
                <DataQualityAlerts issues={narrative.data_quality_issues} citationDocs={citationDocsObj} />
              )}

              {/* Timeline */}
              {narrative.timeline && narrative.timeline.length > 0 && (
                <Timeline events={narrative.timeline} citationDocs={citationDocsObj} />
              )}

              {narrative.synthesized_at && (
                <div style={{ marginTop: 12, fontSize: 10, color: 'var(--muted)', fontStyle: 'italic' }}>
                  Synthesized from {narrative.files_analyzed} analyzed files · {narrative.model_used} · {relativeAge(narrative.synthesized_at)}
                </div>
              )}
            </>
          ) : isAnalyzing ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>⚙️</div>
              <div><strong>Analyzing the corpus…</strong></div>
              <div style={{ fontSize: 11, marginTop: 6 }}>{analysisStatus?.files_with_analysis ?? 0} files analyzed so far</div>
            </div>
          ) : (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              <div>No synthesis yet for {product}.</div>
              <div style={{ fontSize: 11, marginTop: 6 }}>{narrative?.reason ?? 'Run the deep-analysis pipeline.'}</div>
            </div>
          )}
        </div>
      )}

      {/* NARRATIVE (long-form) */}
      {tab === 'narrative' && narrative?.available && (
        <div style={{ marginTop: 12 }}>
          {narrative.narrative_md
            ? <NarrativeMarkdown text={narrative.narrative_md} citationDocs={citationDocsObj} />
            : <div style={{ color: 'var(--muted)', fontSize: 12 }}>No narrative available.</div>
          }

          {/* Source-of-truth override hidden under narrative tab */}
          {cogs?.source_file && (
            <div style={{ marginTop: 16, padding: 10, background: 'var(--panel-2)', borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
                COGS canonical source · {cogs.source_pin_state.auto_chosen ? 'auto' : 'pinned'}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 11 }}>
                <a href={cogs.source_file.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--text)', fontWeight: 600, textDecoration: 'none' }}>
                  📄 {cogs.source_file.name}
                </a>
                <button
                  onClick={() => setShowOverridePicker(s => !s)}
                  style={{ background: 'none', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '2px 8px', borderRadius: 4, fontSize: 10, cursor: 'pointer' }}
                >
                  ✎ change
                </button>
              </div>
              {showOverridePicker && (
                <div style={{ marginTop: 8 }}>
                  <button disabled={overrideSaving} onClick={() => pinSource(null)} style={{ textAlign: 'left', background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.06)', color: 'var(--text)', padding: '4px 8px', borderRadius: 4, fontSize: 10, cursor: 'pointer', marginBottom: 4, width: '100%' }}>
                    ↻ Revert to auto-pick
                  </button>
                  <div style={{ maxHeight: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {revisionsForOverride.map(d => (
                      <button key={d.id} disabled={overrideSaving} onClick={() => pinSource(d.id)} style={{ textAlign: 'left', background: cogs?.source_file?.id === d.id ? 'var(--blue)' : 'var(--panel)', border: '1px solid rgba(255,255,255,0.06)', color: cogs?.source_file?.id === d.id ? '#fff' : 'var(--text)', padding: '4px 8px', borderRadius: 4, fontSize: 10, cursor: 'pointer' }}>
                        <strong>{d.name}</strong>
                      </button>
                    ))}
                  </div>
                  {overrideError && <div style={{ marginTop: 4, fontSize: 10, color: 'var(--red)' }}>{overrideError}</div>}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* FILES drill-down */}
      {tab === 'files' && (
        <div style={{ marginTop: 12 }}>
          {files && files.files.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 600, overflowY: 'auto' }}>
              {files.files.map(f => <FileAnalysisRow key={f.document.id} row={f} />)}
            </div>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 11 }}>No analyzed files yet for {product}.</div>
          )}
        </div>
      )}
    </section>
  )
}

function FileAnalysisRow({ row }: { row: SharepointFileAnalysisRow }) {
  const [open, setOpen] = useState(false)
  const d = row.document
  const factCount = row.key_facts?.length ?? 0
  return (
    <div style={{ background: 'var(--panel-2)', borderRadius: 6, padding: 10, fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <a href={d.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--text)', textDecoration: 'none', fontWeight: 600, flex: 1, minWidth: 200 }} title={d.path}>
          📄 {d.name}
        </a>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: 0.5, padding: '2px 6px', borderRadius: 3, background: 'var(--panel)', color: 'var(--muted)', textTransform: 'uppercase' }}>
          {d.semantic_type ?? '?'}
        </span>
        {d.revision_letter && <span style={{ fontSize: 10, color: 'var(--muted)' }}>rev {d.revision_letter}</span>}
        <button onClick={() => setOpen(o => !o)} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: 11, cursor: 'pointer' }}>
          {open ? 'collapse' : `expand · ${factCount} facts`}
        </button>
      </div>
      {row.purpose && <div style={{ marginTop: 4, color: 'var(--muted)' }}><em>{row.purpose}</em></div>}
      {open && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          {row.key_facts && row.key_facts.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Key facts</div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {row.key_facts.map((f, i) => (
                  <li key={i} style={{ marginBottom: 3 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--panel)', color: 'var(--muted)', textTransform: 'uppercase', marginRight: 6 }}>{f.kind}</span>
                    {f.summary}
                    {f.detail && <span style={{ color: 'var(--muted)' }}> — {f.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {row.related_part_numbers?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11 }}><strong style={{ color: 'var(--muted)' }}>Parts:</strong> {row.related_part_numbers.join(', ')}</div>
          )}
          {row.related_vendors?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11 }}><strong style={{ color: 'var(--muted)' }}>Vendors:</strong> {row.related_vendors.join(', ')}</div>
          )}
          {row.data_quality_flags?.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11, color: 'var(--orange)' }}>⚠ {row.data_quality_flags.join(' · ')}</div>
          )}
        </div>
      )}
    </div>
  )
}
