import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { SharepointVendorWorkspace } from '../lib/api'
import { CollapsibleSection } from './CollapsibleSection'

/**
 * Vendor workspace card — Spider-relevant content pulled from
 * Kienco / Qifei / future vendor SharePoint sites. Backend filters
 * via the keyword classifier in app/services/sharepoint_classify.py
 * so non-Spider content (vendor's own internal stuff, other clients'
 * projects) stays out of view.
 *
 * Layout: collapsible CollapsibleSection. Mini-preview shows tile
 * counts + per-vendor breakdown for at-a-glance visibility. Expanding
 * reveals doc-kind breakdown, per-product split, and click-through
 * recent docs table.
 *
 * Window selector: 30 / 90 / 180 / 365 days. Recent-activity counts
 * drive the urgency cues (orange highlights) on the mini-preview.
 */

const WINDOWS: Array<{ label: string; days: number }> = [
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '180d', days: 180 },
  { label: '365d', days: 365 },
]

const DOC_KIND_LABELS: Record<string, string> = {
  freight_ocean: 'Ocean freight',
  freight_air: 'Air freight',
  shipping: 'Shipping / packing',
  invoice: 'Vendor invoice',
  quote: 'Quote / RFQ',
  patent_ip: 'Patent / IP',
  qa: 'QA / inspection',
  cad_drawing: 'CAD drawing',
  unclassified: 'Other',
}

const DOC_KIND_COLORS: Record<string, string> = {
  freight_ocean: '#6ea8ff',
  freight_air: '#39d08f',
  shipping: '#b88bff',
  invoice: '#ffb257',
  quote: '#f59e0b',
  patent_ip: '#ff6d7a',
  qa: '#39d08f',
  cad_drawing: '#9ca3af',
  unclassified: 'var(--muted)',
}

function fmtRelative(iso: string | null): string {
  if (!iso) return '—'
  const dt = new Date(iso)
  const now = new Date()
  const days = Math.floor((now.getTime() - dt.getTime()) / 86_400_000)
  if (days < 1) return 'today'
  if (days < 2) return 'yesterday'
  if (days < 30) return `${days}d ago`
  if (days < 365) return `${Math.floor(days / 30)}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

interface Props {
  /** Optional override for default open/close. Default: collapsed. */
  defaultOpen?: boolean
}

export function VendorWorkspaceCard({ defaultOpen = false }: Props) {
  const [days, setDays] = useState<number>(90)
  const [data, setData] = useState<SharepointVendorWorkspace | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    const ctl = new AbortController()
    api.sharepointVendorWorkspace(days, ctl.signal)
      .then(setData)
      .catch(err => {
        if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : String(err))
      })
    return () => ctl.abort()
  }, [days])

  // Mini-dashboard preview rendered when collapsed
  const preview = useMemo(() => {
    if (error) return <div style={{ fontSize: 12, color: 'var(--orange)' }}>Error: {error}</div>
    if (!data) return <div style={{ fontSize: 12, color: 'var(--muted)' }}>Loading vendor signals…</div>

    const top3Kinds = data.by_doc_kind.filter(k => k.doc_kind !== 'unclassified').slice(0, 3)

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 8 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
          <Tile label="Vendor sites" value={data.totals.vendor_sites.toString()} />
          <Tile
            label="Spider-relevant docs"
            value={data.totals.spider_relevant.toLocaleString()}
            sublabel={`of ${data.totals.files_total.toLocaleString()} total files`}
          />
          <Tile
            label={`Recent activity (${data.window_days}d)`}
            value={data.totals.recent_activity.toLocaleString()}
            highlight={data.totals.recent_activity > 0}
          />
          <Tile
            label="Doc kinds tagged"
            value={data.totals.doc_kinds_tagged.toLocaleString()}
          />
        </div>

        {/* Inline by-vendor + top doc kinds for at-a-glance */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 11, color: 'var(--muted)' }}>
          {data.by_vendor.map(v => (
            <div key={v.site_path}>
              <strong style={{ color: 'var(--text)' }}>{v.display_name}</strong>:{' '}
              {v.spider_relevant} Spider docs
              {v.recent_activity_in_window > 0 ? (
                <span style={{ color: 'var(--orange)', marginLeft: 4 }}>
                  · {v.recent_activity_in_window} recent
                </span>
              ) : null}
            </div>
          ))}
        </div>

        {top3Kinds.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {top3Kinds.map(k => (
              <span
                key={k.doc_kind}
                style={{
                  fontSize: 10,
                  padding: '2px 8px',
                  borderRadius: 10,
                  border: `1px solid ${DOC_KIND_COLORS[k.doc_kind] || 'var(--border)'}`,
                  color: DOC_KIND_COLORS[k.doc_kind] || 'var(--muted)',
                }}
              >
                {DOC_KIND_LABELS[k.doc_kind] || k.doc_kind}: {k.count}
                {k.recent_in_window > 0 ? ` (${k.recent_in_window} new)` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }, [data, error])

  // Expanded full content
  const expanded = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Window selector */}
      <div style={{ display: 'flex', gap: 6 }}>
        {WINDOWS.map(w => (
          <button
            key={w.days}
            onClick={() => setDays(w.days)}
            className={`range-button${days === w.days ? ' active' : ''}`}
            style={{ fontSize: 11 }}
          >
            {w.label}
          </button>
        ))}
      </div>

      {error && <div className="state-message" style={{ color: 'var(--orange)' }}>Error: {error}</div>}
      {!data && !error && <div className="state-message">Loading…</div>}
      {data && (
        <>
          {/* By doc kind */}
          {data.by_doc_kind.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                By document kind
              </div>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>Kind</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Total</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Recent ({days}d)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_doc_kind.map(k => (
                    <tr key={k.doc_kind} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '4px 8px' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: DOC_KIND_COLORS[k.doc_kind] || 'var(--muted)',
                            marginRight: 6,
                          }}
                        />
                        {DOC_KIND_LABELS[k.doc_kind] || k.doc_kind}
                      </td>
                      <td style={{ textAlign: 'right', padding: '4px 8px' }}>{k.count}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px',
                        color: k.recent_in_window > 0 ? 'var(--orange)' : undefined,
                        fontWeight: k.recent_in_window > 0 ? 600 : 400,
                      }}>
                        {k.recent_in_window || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* By Spider product */}
          {data.by_spider_product.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                By Spider product
              </div>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>Product</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Total</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Recent ({days}d)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_spider_product.map(p => (
                    <tr key={p.spider_product} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '4px 8px' }}>{p.spider_product}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px' }}>{p.count}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px',
                        color: p.recent_in_window > 0 ? 'var(--orange)' : undefined,
                      }}>
                        {p.recent_in_window || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Recent docs (click-through) */}
          {data.recent_docs.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                Most recent {data.recent_docs.length} Spider-relevant docs
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>File</th>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Vendor</th>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Product</th>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Kind</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>Modified</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_docs.map(d => (
                      <tr key={d.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '4px 8px', maxWidth: 360 }}>
                          {d.web_url ? (
                            <a
                              href={d.web_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: 'var(--blue)', textDecoration: 'none' }}
                            >
                              {d.name}
                            </a>
                          ) : (
                            <span>{d.name}</span>
                          )}
                        </td>
                        <td style={{ padding: '4px 8px', color: 'var(--muted)', fontSize: 11 }}>
                          {d.vendor_display_name}
                        </td>
                        <td style={{ padding: '4px 8px' }}>{d.spider_product || '—'}</td>
                        <td style={{ padding: '4px 8px' }}>
                          {d.detected_doc_kind ? (
                            <span style={{
                              fontSize: 10,
                              padding: '1px 6px',
                              borderRadius: 8,
                              background: 'rgba(255,255,255,0.05)',
                              color: DOC_KIND_COLORS[d.detected_doc_kind] || 'var(--muted)',
                            }}>
                              {DOC_KIND_LABELS[d.detected_doc_kind] || d.detected_doc_kind}
                            </span>
                          ) : <span style={{ color: 'var(--muted)' }}>—</span>}
                        </td>
                        <td style={{ textAlign: 'right', padding: '4px 8px', color: 'var(--muted)' }}>
                          {fmtRelative(d.modified_at_remote)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
            {data.method_note}
          </div>
        </>
      )}
    </div>
  )

  return (
    <CollapsibleSection
      id="vendor-workspace"
      title="Vendor inbound — Kienco · Qifei"
      subtitle="Spider-relevant docs from vendor SharePoint workspaces"
      defaultOpen={defaultOpen}
      accentColor="#b88bff"
      preview={preview}
    >
      {expanded}
    </CollapsibleSection>
  )
}

function Tile({ label, value, sublabel, highlight }: {
  label: string
  value: string
  sublabel?: string
  highlight?: boolean
}) {
  return (
    <div style={{
      padding: '6px 10px',
      background: 'rgba(255,255,255,0.03)',
      borderRadius: 6,
      borderLeft: highlight ? '2px solid var(--orange)' : undefined,
    }}>
      <div style={{ fontSize: 10, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700 }}>{value}</div>
      {sublabel && <div style={{ fontSize: 9, color: 'var(--muted)' }}>{sublabel}</div>}
    </div>
  )
}
