import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type {
  SharepointActiveArchive,
  SharepointCogsResponse,
  SharepointDocSummary,
  SharepointExtractionStatus,
  SharepointRevisions,
  SharepointVendorDirectory,
} from '../lib/api'

/**
 * Per-product SharePoint intelligence card.
 *
 * Replaces the dumb "list of recently modified files" feed with
 * structured, semantically meaningful data extracted from the corpus:
 *
 *   - COGS rollup: total cost + line count + vendor breakdown for the
 *     canonical BOM/CBOM. Click-through to the source-of-truth file.
 *     Page owner can override which file is canonical via the pencil
 *     icon → revisions list → "pin this".
 *   - Vendor directory: who we buy from, ranked by line count.
 *   - Active vs archived split: how much of the corpus for this
 *     product is live vs deprecated, by semantic type.
 *   - Extraction freshness chip: "X / Y BOMs parsed" so the user knows
 *     how complete the rollup is.
 *
 * Props:
 *   - division: 'pe' | 'operations' | 'manufacturing' (constrains
 *     scope display; vendors and COGS still pull cross-division for
 *     accuracy)
 *   - product: optional Spider product to focus on. If omitted, the
 *     user picks via the product tab strip.
 */

const PRODUCTS = ['Huntsman', 'Giant Huntsman', 'Venom', 'Webcraft', 'Giant Webcraft'] as const
type Product = (typeof PRODUCTS)[number]

interface Props {
  division: 'pe' | 'operations' | 'manufacturing'
  defaultProduct?: Product
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso.slice(0, 10)
  }
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

export function SharepointIntelligenceCard({ division, defaultProduct }: Props) {
  const [product, setProduct] = useState<Product>(defaultProduct ?? 'Huntsman')
  const [cogs, setCogs] = useState<SharepointCogsResponse | null>(null)
  const [vendors, setVendors] = useState<SharepointVendorDirectory | null>(null)
  const [activeArchive, setActiveArchive] = useState<SharepointActiveArchive | null>(null)
  const [extraction, setExtraction] = useState<SharepointExtractionStatus | null>(null)
  const [revisions, setRevisions] = useState<SharepointRevisions | null>(null)
  const [showOverridePicker, setShowOverridePicker] = useState(false)
  const [overrideError, setOverrideError] = useState<string | null>(null)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [tab, setTab] = useState<'cogs' | 'vendors' | 'corpus' | 'revisions'>('cogs')

  useEffect(() => {
    const ctl = new AbortController()
    Promise.all([
      api.sharepointCogs({ spider_product: product }, ctl.signal).then(setCogs).catch(() => setCogs(null)),
      api.sharepointVendors(product, ctl.signal).then(setVendors).catch(() => setVendors(null)),
      api.sharepointActiveArchive({ spider_product: product, division }, ctl.signal).then(setActiveArchive).catch(() => setActiveArchive(null)),
      api.sharepointExtractionStatus(ctl.signal).then(setExtraction).catch(() => setExtraction(null)),
    ]).catch(() => undefined)
    return () => ctl.abort()
  }, [product, division])

  // Load revisions only when the user opens the picker or the revisions tab
  useEffect(() => {
    if (!showOverridePicker && tab !== 'revisions') return
    const ctl = new AbortController()
    api.sharepointRevisions(product, 'bom', ctl.signal)
      .then(setRevisions)
      .catch(() => setRevisions(null))
    return () => ctl.abort()
  }, [showOverridePicker, tab, product])

  const candidateRevisions = useMemo<SharepointDocSummary[]>(() => {
    if (!revisions) return []
    return revisions.by_assembly.flatMap(b => b.revisions)
  }, [revisions])

  async function pinSource(docId: number | null, note?: string) {
    setOverrideSaving(true)
    setOverrideError(null)
    try {
      await api.sharepointSetCanonical({
        data_type: 'cogs',
        spider_product: product,
        dashboard_division: null,
        document_id: docId,
        note: note ?? null,
      })
      // Refetch COGS so the new pin state shows
      const fresh = await api.sharepointCogs({ spider_product: product })
      setCogs(fresh)
      setShowOverridePicker(false)
    } catch (err) {
      setOverrideError(err instanceof Error ? err.message : 'Failed to set override (check auth)')
    } finally {
      setOverrideSaving(false)
    }
  }

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>SharePoint intelligence</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Active corpus parsed into structured data. Source-of-truth
            files are linked inline; click the pencil to override which
            file the dashboard uses.
          </div>
        </div>
        {extraction && (
          <span
            title={`Last extraction run: ${extraction.last_extraction_at ?? '—'}`}
            style={{
              fontSize: 10,
              padding: '3px 8px',
              borderRadius: 4,
              background: 'var(--panel-2)',
              color: 'var(--muted)',
              fontWeight: 600,
              letterSpacing: 0.4,
            }}
          >
            {extraction.extracted_successfully}/{extraction.active_bom_docs} BOMs parsed · {fmtInt(extraction.bom_lines_total)} lines
          </span>
        )}
      </div>

      {/* Product tabs */}
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
        {(['cogs', 'vendors', 'corpus', 'revisions'] as const).map(t => (
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
            {t === 'cogs' ? 'COGS rollup' : t === 'vendors' ? 'Vendors' : t === 'corpus' ? 'Active vs Archived' : 'Revisions'}
          </button>
        ))}
      </div>

      {/* COGS tab */}
      {tab === 'cogs' && (
        <div style={{ marginTop: 12 }}>
          {/* Source of truth header */}
          <div style={{ background: 'var(--panel-2)', padding: 12, borderRadius: 6, borderLeft: '3px solid var(--blue)' }}>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
              Source of truth · {cogs?.source_pin_state.auto_chosen ? 'auto-picked' : 'pinned'}
            </div>
            {cogs?.source_file ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <a
                  href={cogs.source_file.web_url ?? '#'}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: 'var(--text)', textDecoration: 'none', fontWeight: 600, fontSize: 13 }}
                  title={cogs.source_file.path}
                >
                  📄 {cogs.source_file.name}
                </a>
                <button
                  onClick={() => setShowOverridePicker(s => !s)}
                  title="Change which file is the source of truth"
                  style={{
                    background: 'none',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: 'var(--muted)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    cursor: 'pointer',
                  }}
                >
                  ✎ change
                </button>
                {!cogs.source_pin_state.auto_chosen && (
                  <span style={{ fontSize: 10, color: 'var(--orange)', fontWeight: 600 }}>
                    pinned by {cogs.source_pin_state.override_user || 'unknown'} · {relativeAge(cogs.source_pin_state.override_at)}
                  </span>
                )}
                <small style={{ color: 'var(--muted)', flexBasis: '100%', fontSize: 11 }}>
                  rev <strong>{cogs.source_file.revision_letter ?? '?'}</strong> · {fmtDate(cogs.source_file.doc_date)} · modified {relativeAge(cogs.source_file.modified_at)} by{' '}
                  {cogs.source_file.modified_by_email?.split('@')[0] ?? '—'}
                </small>
              </div>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>No canonical BOM file found for {product}.</div>
            )}

            {showOverridePicker && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
                  Pick a different file as source of truth, or revert to auto.
                </div>
                <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <button
                    disabled={overrideSaving}
                    onClick={() => pinSource(null, 'reverted to auto')}
                    style={{
                      textAlign: 'left',
                      background: 'var(--panel)',
                      border: '1px solid rgba(255,255,255,0.06)',
                      color: 'var(--text)',
                      padding: '6px 10px',
                      borderRadius: 4,
                      fontSize: 11,
                      cursor: 'pointer',
                    }}
                  >
                    ↻ Revert to auto-pick
                  </button>
                  {candidateRevisions.map(d => (
                    <button
                      key={d.id}
                      disabled={overrideSaving}
                      onClick={() => pinSource(d.id, `pinned via SharePoint intelligence card`)}
                      style={{
                        textAlign: 'left',
                        background: cogs?.source_file?.id === d.id ? 'var(--blue)' : 'var(--panel)',
                        border: '1px solid rgba(255,255,255,0.06)',
                        color: cogs?.source_file?.id === d.id ? '#fff' : 'var(--text)',
                        padding: '6px 10px',
                        borderRadius: 4,
                        fontSize: 11,
                        cursor: 'pointer',
                      }}
                    >
                      <strong>{d.name}</strong>
                      <div style={{ fontSize: 10, opacity: 0.75 }}>
                        rev {d.revision_letter ?? '?'} · {fmtDate(d.doc_date)} · {d.archive_status}
                      </div>
                    </button>
                  ))}
                </div>
                {overrideError && (
                  <div style={{ marginTop: 6, fontSize: 11, color: 'var(--red)' }}>{overrideError}</div>
                )}
              </div>
            )}
          </div>

          {/* Rollup totals */}
          {cogs && cogs.source_file ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10, marginTop: 10 }}>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Total COGS</div>
                <div className="kpi-tile-value">{fmtUSD(cogs.rollup.total_cost_usd)}</div>
                <div className="kpi-tile-sub">extracted from canonical BOM</div>
              </div>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Line items</div>
                <div className="kpi-tile-value">{fmtInt(cogs.rollup.line_count)}</div>
                <div className="kpi-tile-sub">parts in BOM</div>
              </div>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Vendors</div>
                <div className="kpi-tile-value">{fmtInt(cogs.rollup.vendor_count)}</div>
                <div className="kpi-tile-sub">named in this BOM</div>
              </div>
            </div>
          ) : null}

          {/* Vendor breakdown for this product's BOM */}
          {cogs && cogs.rollup.vendors.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
                Vendors on canonical BOM
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12 }}>
                {cogs.rollup.vendors.slice(0, 10).map(v => (
                  <div key={v.vendor} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 12, padding: '4px 8px', background: 'var(--panel-2)', borderRadius: 4 }}>
                    <span title={v.vendor}>{v.vendor.length > 60 ? v.vendor.slice(0, 60) + '…' : v.vendor}</span>
                    <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>{v.lines} line{v.lines === 1 ? '' : 's'}</span>
                    <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmtUSD(v.cost)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Line items table (collapsed if >20) */}
          {cogs && cogs.lines.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Line items ({cogs.lines.length})
              </summary>
              <div style={{ maxHeight: 320, overflowY: 'auto', fontSize: 11, marginTop: 6 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
                  <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)', textAlign: 'left' }}>
                    <tr style={{ color: 'var(--muted)' }}>
                      <th style={{ padding: '4px 6px' }}>#</th>
                      <th style={{ padding: '4px 6px' }}>Part</th>
                      <th style={{ padding: '4px 6px' }}>Description</th>
                      <th style={{ padding: '4px 6px' }}>Vendor</th>
                      <th style={{ padding: '4px 6px', textAlign: 'right' }}>Qty</th>
                      <th style={{ padding: '4px 6px', textAlign: 'right' }}>Unit</th>
                      <th style={{ padding: '4px 6px', textAlign: 'right' }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cogs.lines.map((l, i) => (
                      <tr key={i} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '4px 6px', color: 'var(--muted)' }}>{l.line_no ?? i + 1}</td>
                        <td style={{ padding: '4px 6px', fontWeight: 600 }}>{l.part_number ?? '—'}</td>
                        <td style={{ padding: '4px 6px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={l.description ?? ''}>
                          {l.description ?? ''}
                        </td>
                        <td style={{ padding: '4px 6px', color: 'var(--muted)' }}>{l.vendor_name ?? ''}</td>
                        <td style={{ padding: '4px 6px', textAlign: 'right' }}>{l.qty != null ? l.qty.toFixed(2) : ''}</td>
                        <td style={{ padding: '4px 6px', textAlign: 'right' }}>{l.unit_cost_usd != null ? fmtUSD(l.unit_cost_usd) : ''}</td>
                        <td style={{ padding: '4px 6px', textAlign: 'right' }}>{l.total_cost_usd != null ? fmtUSD(l.total_cost_usd) : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}

      {/* Vendors tab */}
      {tab === 'vendors' && (
        <div style={{ marginTop: 12, fontSize: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
            Cross-BOM vendor directory for {product}. Aggregates every line of every active BOM/CBOM/price-list.
          </div>
          {vendors && vendors.vendors.length > 0 ? (
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
                <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)', textAlign: 'left' }}>
                  <tr style={{ color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    <th style={{ padding: '4px 6px' }}>Vendor</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Docs</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Lines</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Total cost</th>
                  </tr>
                </thead>
                <tbody>
                  {vendors.vendors.slice(0, 80).map(v => (
                    <tr key={v.vendor} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding: '4px 6px', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v.vendor}>
                        {v.vendor}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{v.doc_count}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{v.line_count}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtUSD(v.total_cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 11 }}>No vendor names extracted from BOMs for {product} yet.</div>
          )}
        </div>
      )}

      {/* Corpus tab */}
      {tab === 'corpus' && activeArchive && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 10 }}>
            <div className="kpi-tile">
              <div className="kpi-tile-label">Active</div>
              <div className="kpi-tile-value" style={{ color: 'var(--green)' }}>{fmtInt(activeArchive.by_status.active ?? 0)}</div>
            </div>
            <div className="kpi-tile">
              <div className="kpi-tile-label">Archived</div>
              <div className="kpi-tile-value" style={{ color: 'var(--muted)' }}>{fmtInt(activeArchive.by_status.archived ?? 0)}</div>
            </div>
          </div>
          <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
            By semantic type
          </div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
            <thead>
              <tr style={{ color: 'var(--muted)', textAlign: 'left', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                <th style={{ padding: '4px 6px' }}>Type</th>
                <th style={{ padding: '4px 6px', textAlign: 'right' }}>Active</th>
                <th style={{ padding: '4px 6px', textAlign: 'right' }}>Archived</th>
                <th style={{ padding: '4px 6px', textAlign: 'right' }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {activeArchive.by_semantic_type.map(r => (
                <tr key={r.semantic_type} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '4px 6px' }}>{r.semantic_type}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtInt(r.active)}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--muted)' }}>{fmtInt(r.archived)}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>{fmtInt(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Revisions tab */}
      {tab === 'revisions' && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
            Every BOM revision for {product}, grouped by assembly. Click any to open in SharePoint.
          </div>
          {revisions ? (
            revisions.by_assembly.map(b => (
              <div key={b.assembly_name} style={{ marginBottom: 14 }}>
                <strong style={{ fontSize: 12 }}>{b.assembly_name}</strong>
                <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>{b.revisions.length} rev{b.revisions.length === 1 ? '' : 's'}</span>
                <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {b.revisions.map(r => (
                    <a
                      key={r.id}
                      href={r.web_url ?? '#'}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'auto 1fr auto auto auto',
                        gap: 8,
                        padding: '4px 8px',
                        background: 'var(--panel-2)',
                        borderRadius: 4,
                        textDecoration: 'none',
                        color: 'var(--text)',
                        fontSize: 11,
                        alignItems: 'center',
                      }}
                    >
                      <span style={{ color: 'var(--muted)', fontWeight: 600 }}>rev {r.revision_letter ?? '?'}</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                      <span style={{ color: 'var(--muted)' }}>{fmtDate(r.doc_date)}</span>
                      <span style={{ color: r.archive_status === 'archived' ? 'var(--muted)' : 'var(--green)', fontSize: 9, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' }}>
                        {r.archive_status}
                      </span>
                      {cogs?.source_file?.id === r.id && (
                        <span style={{ fontSize: 9, color: 'var(--blue)', fontWeight: 700, letterSpacing: 0.5 }}>★ CANONICAL</span>
                      )}
                    </a>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 11 }}>Loading revisions…</div>
          )}
        </div>
      )}
    </section>
  )
}
