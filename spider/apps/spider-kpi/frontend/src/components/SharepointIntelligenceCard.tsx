import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type {
  SharepointActiveArchive,
  SharepointAnalysisStatusResponse,
  SharepointCogsResponse,
  SharepointDocSummary,
  SharepointFileAnalysisRow,
  SharepointFileAnalysesResponse,
  SharepointProductNarrative,
  SharepointVendorDirectory,
} from '../lib/api'

/**
 * Per-product SharePoint intelligence card — narrative-first.
 *
 * Top of the card is the synthesized narrative from
 * /api/sharepoint/intelligence/product-narrative — Opus 4.7's
 * cross-file reading of the corpus, with [doc:N] citations
 * rendered as inline links to the source files.
 *
 * Below the narrative, structured rollups expose the typed
 * sub-payloads (COGS confidence, design status, top vendors, data
 * quality issues). Underneath those, the file drill-down shows
 * every analyzed file's purpose + key facts + parts/vendors.
 *
 * Source-of-truth file links use the same canonical override
 * mechanism as before so Joseph and page owners can pin which file
 * the dashboard uses for each datapoint.
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

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'var(--red)',
  warn: 'var(--orange)',
  info: 'var(--blue)',
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
  // Simple line-aware markdown renderer with [doc:N] handling.
  // Splits on blank lines into paragraphs, recognizes - bullets and
  // ## headings.
  const blocks = useMemo(() => text.split(/\n\n+/), [text])

  function renderInline(s: string, keyPrefix: string): JSX.Element[] {
    // Tokenize on [doc:N] and **bold**
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
          <a
            key={`${keyPrefix}-${i++}`}
            href={doc?.web_url ?? '#'}
            target="_blank"
            rel="noreferrer"
            title={doc ? `${doc.name} — ${doc.path}` : `doc ${id}`}
            style={{
              color: 'var(--blue)',
              textDecoration: 'none',
              fontSize: '0.85em',
              verticalAlign: 'super',
              lineHeight: 1,
              padding: '0 2px',
            }}
          >
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
    <div style={{ lineHeight: 1.6, fontSize: 13.5, color: 'var(--text)' }}>
      {blocks.map((block, bi) => {
        const trimmed = block.trim()
        if (!trimmed) return null
        // Heading
        if (trimmed.startsWith('## ')) {
          return (
            <h4 key={bi} style={{ fontSize: 14, marginTop: 14, marginBottom: 6, color: 'var(--text)' }}>
              {renderInline(trimmed.slice(3), `h-${bi}`)}
            </h4>
          )
        }
        if (trimmed.startsWith('# ')) {
          return (
            <h3 key={bi} style={{ fontSize: 15, marginTop: 14, marginBottom: 6, color: 'var(--text)' }}>
              {renderInline(trimmed.slice(2), `h-${bi}`)}
            </h3>
          )
        }
        // Bullet list block
        if (trimmed.split('\n').every(l => /^\s*[-*]\s/.test(l))) {
          return (
            <ul key={bi} style={{ paddingLeft: 18, margin: '6px 0' }}>
              {trimmed.split('\n').map((l, li) => (
                <li key={li} style={{ marginBottom: 3 }}>
                  {renderInline(l.replace(/^\s*[-*]\s/, ''), `bul-${bi}-${li}`)}
                </li>
              ))}
            </ul>
          )
        }
        // Paragraph
        return (
          <p key={bi} style={{ margin: '8px 0' }}>
            {renderInline(trimmed.replace(/\n/g, ' '), `p-${bi}`)}
          </p>
        )
      })}
    </div>
  )
}

export function SharepointIntelligenceCard({ division, defaultProduct }: Props) {
  const [product, setProduct] = useState<Product>(defaultProduct ?? 'Huntsman')
  const [narrative, setNarrative] = useState<SharepointProductNarrative | null>(null)
  const [cogs, setCogs] = useState<SharepointCogsResponse | null>(null)
  const [vendors, setVendors] = useState<SharepointVendorDirectory | null>(null)
  const [activeArchive, setActiveArchive] = useState<SharepointActiveArchive | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<SharepointAnalysisStatusResponse | null>(null)
  const [files, setFiles] = useState<SharepointFileAnalysesResponse | null>(null)
  const [tab, setTab] = useState<'narrative' | 'cogs' | 'files' | 'corpus'>('narrative')
  const [showOverridePicker, setShowOverridePicker] = useState(false)
  const [overrideError, setOverrideError] = useState<string | null>(null)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [revisionsForOverride, setRevisionsForOverride] = useState<SharepointDocSummary[]>([])

  useEffect(() => {
    const ctl = new AbortController()
    Promise.all([
      api.sharepointProductNarrative(product, ctl.signal).then(setNarrative).catch(() => setNarrative(null)),
      api.sharepointCogs({ spider_product: product }, ctl.signal).then(setCogs).catch(() => setCogs(null)),
      api.sharepointVendors(product, ctl.signal).then(setVendors).catch(() => setVendors(null)),
      api.sharepointActiveArchive({ spider_product: product, division }, ctl.signal).then(setActiveArchive).catch(() => setActiveArchive(null)),
      api.sharepointAnalysisStatus(ctl.signal).then(setAnalysisStatus).catch(() => setAnalysisStatus(null)),
      api.sharepointFileAnalyses({ spider_product: product }, ctl.signal).then(setFiles).catch(() => setFiles(null)),
    ]).catch(() => undefined)
    return () => ctl.abort()
  }, [product, division])

  // Lazy-load revisions only when the override picker opens
  useEffect(() => {
    if (!showOverridePicker) return
    const ctl = new AbortController()
    api.sharepointRevisions(product, 'bom', ctl.signal)
      .then(rev => setRevisionsForOverride(rev.by_assembly.flatMap(b => b.revisions)))
      .catch(() => setRevisionsForOverride([]))
    return () => ctl.abort()
  }, [showOverridePicker, product])

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
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>SharePoint intelligence — {product}</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            AI-synthesized narrative across the corpus. Every claim cites the
            source file — click [N] to open in SharePoint.
          </div>
        </div>
        {analysisStatus && (
          <span
            title={`Last extraction: ${analysisStatus.last_content_extracted_at ?? '—'}\nLast analysis: ${analysisStatus.last_analysis_at ?? '—'}\nLast synthesis: ${analysisStatus.last_synthesis_at ?? '—'}`}
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
            {fmtInt(analysisStatus.files_with_analysis)} files analyzed · {analysisStatus.products_with_synthesis} products synthesized
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
        {(['narrative', 'cogs', 'files', 'corpus'] as const).map(t => (
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
            {t === 'narrative' ? 'Narrative' : t === 'cogs' ? 'COGS' : t === 'files' ? 'Files (' + (files?.files.length ?? 0) + ')' : 'Corpus'}
          </button>
        ))}
      </div>

      {/* NARRATIVE TAB */}
      {tab === 'narrative' && (
        <div style={{ marginTop: 12 }}>
          {narrative?.available && narrative.narrative_md ? (
            <>
              <NarrativeMarkdown text={narrative.narrative_md} citationDocs={citationDocsObj} />

              {/* COGS quick read */}
              {narrative.cogs_summary && (
                <div style={{
                  marginTop: 14,
                  padding: 10,
                  background: 'var(--panel-2)',
                  borderRadius: 6,
                  borderLeft: `3px solid ${
                    narrative.cogs_summary.confidence === 'high' ? 'var(--green)'
                    : narrative.cogs_summary.confidence === 'medium' ? 'var(--orange)'
                    : 'var(--red)'
                  }`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <strong style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)' }}>COGS read</strong>
                    <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.5, padding: '1px 6px', borderRadius: 3, background: 'var(--panel)' }}>
                      confidence: {narrative.cogs_summary.confidence}
                    </span>
                  </div>
                  <div style={{ marginTop: 4, fontSize: 13 }}>
                    {narrative.cogs_summary.canonical_total_usd != null
                      ? <><strong>{fmtUSD(narrative.cogs_summary.canonical_total_usd)}</strong> across {fmtInt(narrative.cogs_summary.canonical_line_count)} lines</>
                      : <em style={{ color: 'var(--muted)' }}>No reliable total available</em>
                    }
                    {narrative.cogs_summary.canonical_document_id && citationDocsObj[String(narrative.cogs_summary.canonical_document_id)] && (
                      <span style={{ color: 'var(--muted)', marginLeft: 8, fontSize: 11 }}>
                        from <a href={citationDocsObj[String(narrative.cogs_summary.canonical_document_id)].web_url ?? '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--blue)' }}>
                          {citationDocsObj[String(narrative.cogs_summary.canonical_document_id)].name}
                        </a>
                      </span>
                    )}
                  </div>
                  {narrative.cogs_summary.notes && (
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>{narrative.cogs_summary.notes}</div>
                  )}
                </div>
              )}

              {/* Data quality issues */}
              {narrative.data_quality_issues && narrative.data_quality_issues.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Data quality issues
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {narrative.data_quality_issues.map((iss, i) => (
                      <div key={i} style={{
                        padding: '6px 10px',
                        background: 'var(--panel-2)',
                        borderLeft: `3px solid ${SEVERITY_COLOR[iss.severity] || 'var(--muted)'}`,
                        borderRadius: 4,
                        fontSize: 12,
                      }}>
                        <span style={{ color: SEVERITY_COLOR[iss.severity] || 'var(--muted)', fontWeight: 700, fontSize: 9, letterSpacing: 0.5, textTransform: 'uppercase', marginRight: 8 }}>
                          {iss.severity}
                        </span>
                        {iss.issue}
                        {iss.suggested_fix && (
                          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                            <strong>Fix:</strong> {iss.suggested_fix}
                          </div>
                        )}
                        {iss.affected_document_ids && iss.affected_document_ids.length > 0 && (
                          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                            {iss.affected_document_ids.map(id => {
                              const d = citationDocsObj[String(id)]
                              return d ? (
                                <a key={id} href={d.web_url ?? '#'} target="_blank" rel="noreferrer" style={{ marginRight: 8, color: 'var(--blue)' }}>
                                  📄 {d.name.length > 40 ? d.name.slice(0, 40) + '…' : d.name}
                                </a>
                              ) : <span key={id} style={{ marginRight: 6 }}>doc:{id}</span>
                            })}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Active workstreams */}
              {narrative.design_status?.active_workstreams && narrative.design_status.active_workstreams.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Active workstreams
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.6 }}>
                    {narrative.design_status.active_workstreams.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              {/* Top vendors */}
              {narrative.vendor_summary?.top_vendors && narrative.vendor_summary.top_vendors.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Top vendors ({narrative.vendor_summary.total_unique} unique)
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, fontSize: 11 }}>
                    {narrative.vendor_summary.top_vendors.slice(0, 12).map(v => (
                      <span key={v.name} style={{ padding: '3px 8px', background: 'var(--panel-2)', borderRadius: 4 }}>
                        <strong>{v.name}</strong>
                        {v.role && <span style={{ color: 'var(--muted)', marginLeft: 4 }}>· {v.role}</span>}
                        <span style={{ color: 'var(--muted)', marginLeft: 4 }}>· {v.documents_seen}d</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {narrative.synthesized_at && (
                <div style={{ marginTop: 14, fontSize: 10, color: 'var(--muted)', fontStyle: 'italic' }}>
                  Synthesized from {narrative.files_analyzed} analyzed files · {narrative.model_used} · {relativeAge(narrative.synthesized_at)}
                </div>
              )}
            </>
          ) : isAnalyzing ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>⚙️</div>
              <div><strong>Analyzing the corpus…</strong></div>
              <div style={{ fontSize: 11, marginTop: 6 }}>
                {analysisStatus?.files_with_analysis ?? 0} files analyzed so far · check back in a few minutes
              </div>
            </div>
          ) : (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              <div>No synthesis yet for {product}.</div>
              <div style={{ fontSize: 11, marginTop: 6 }}>
                {narrative?.reason ?? 'Run the deep-analysis pipeline.'}
              </div>
            </div>
          )}
        </div>
      )}

      {/* COGS TAB — kept from v1 for the canonical-source override flow */}
      {tab === 'cogs' && (
        <div style={{ marginTop: 12 }}>
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
              </div>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>No canonical BOM file found for {product}.</div>
            )}
            {showOverridePicker && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
                  Pick a different file as source of truth, or revert to auto.
                </div>
                <div style={{ maxHeight: 240, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <button disabled={overrideSaving} onClick={() => pinSource(null)} style={{ textAlign: 'left', background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.06)', color: 'var(--text)', padding: '6px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>
                    ↻ Revert to auto-pick
                  </button>
                  {revisionsForOverride.map(d => (
                    <button key={d.id} disabled={overrideSaving} onClick={() => pinSource(d.id)} style={{ textAlign: 'left', background: cogs?.source_file?.id === d.id ? 'var(--blue)' : 'var(--panel)', border: '1px solid rgba(255,255,255,0.06)', color: cogs?.source_file?.id === d.id ? '#fff' : 'var(--text)', padding: '6px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>
                      <strong>{d.name}</strong>
                      <div style={{ fontSize: 10, opacity: 0.75 }}>rev {d.revision_letter ?? '?'} · {d.doc_date ?? '—'}</div>
                    </button>
                  ))}
                </div>
                {overrideError && (<div style={{ marginTop: 6, fontSize: 11, color: 'var(--red)' }}>{overrideError}</div>)}
              </div>
            )}
          </div>

          {cogs && cogs.source_file && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10, marginTop: 10 }}>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Total COGS</div>
                <div className="kpi-tile-value">{fmtUSD(cogs.rollup.total_cost_usd)}</div>
                <div className="kpi-tile-sub">from canonical BOM</div>
              </div>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Line items</div>
                <div className="kpi-tile-value">{fmtInt(cogs.rollup.line_count)}</div>
              </div>
              <div className="kpi-tile">
                <div className="kpi-tile-label">Vendors</div>
                <div className="kpi-tile-value">{fmtInt(cogs.rollup.vendor_count)}</div>
              </div>
            </div>
          )}
          {cogs && cogs.lines.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Line items ({cogs.lines.length})
              </summary>
              <div style={{ maxHeight: 320, overflowY: 'auto', fontSize: 11, marginTop: 6 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
                  <thead style={{ position: 'sticky', top: 0, background: 'var(--panel)', textAlign: 'left' }}>
                    <tr style={{ color: 'var(--muted)' }}>
                      <th style={{ padding: '4px 6px' }}>#</th><th style={{ padding: '4px 6px' }}>Part</th><th style={{ padding: '4px 6px' }}>Description</th><th style={{ padding: '4px 6px' }}>Vendor</th><th style={{ padding: '4px 6px', textAlign: 'right' }}>Qty</th><th style={{ padding: '4px 6px', textAlign: 'right' }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cogs.lines.map((l, i) => (
                      <tr key={i} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '4px 6px', color: 'var(--muted)' }}>{l.line_no ?? i + 1}</td>
                        <td style={{ padding: '4px 6px', fontWeight: 600 }}>{l.part_number ?? '—'}</td>
                        <td style={{ padding: '4px 6px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={l.description ?? ''}>{l.description ?? ''}</td>
                        <td style={{ padding: '4px 6px', color: 'var(--muted)' }}>{l.vendor_name ?? ''}</td>
                        <td style={{ padding: '4px 6px', textAlign: 'right' }}>{l.qty != null ? l.qty.toFixed(2) : ''}</td>
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

      {/* FILES TAB — drill-down: every analyzed file with purpose + facts */}
      {tab === 'files' && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
            Every analyzed file for {product}. Click the file name to open in SharePoint.
          </div>
          {files && files.files.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 600, overflowY: 'auto' }}>
              {files.files.map(f => (
                <FileAnalysisRow key={f.document.id} row={f} />
              ))}
            </div>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 11 }}>No analyzed files yet for {product}.</div>
          )}
        </div>
      )}

      {/* CORPUS TAB */}
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
            <div className="kpi-tile">
              <div className="kpi-tile-label">Analyzed</div>
              <div className="kpi-tile-value" style={{ color: 'var(--blue)' }}>{fmtInt(files?.files.length ?? 0)}</div>
              <div className="kpi-tile-sub">deep AI pass</div>
            </div>
          </div>
          <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
            By semantic type
          </div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
            <thead>
              <tr style={{ color: 'var(--muted)', textAlign: 'left', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                <th style={{ padding: '4px 6px' }}>Type</th><th style={{ padding: '4px 6px', textAlign: 'right' }}>Active</th><th style={{ padding: '4px 6px', textAlign: 'right' }}>Archived</th><th style={{ padding: '4px 6px', textAlign: 'right' }}>Total</th>
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
        {d.revision_letter && (
          <span style={{ fontSize: 10, color: 'var(--muted)' }}>rev {d.revision_letter}</span>
        )}
        <button onClick={() => setOpen(o => !o)} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: 11, cursor: 'pointer' }}>
          {open ? 'collapse' : `expand · ${factCount} facts`}
        </button>
      </div>
      {row.purpose && (
        <div style={{ marginTop: 4, color: 'var(--muted)' }}>
          <em>{row.purpose}</em>
        </div>
      )}
      {open && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          {row.key_facts && row.key_facts.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Key facts</div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {row.key_facts.map((f, i) => (
                  <li key={i} style={{ marginBottom: 3 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: 0.5, padding: '1px 5px', borderRadius: 3, background: 'var(--panel)', color: 'var(--muted)', textTransform: 'uppercase', marginRight: 6 }}>{f.kind}</span>
                    {f.summary}
                    {f.detail && <span style={{ color: 'var(--muted)' }}> — {f.detail}</span>}
                    {f.source_location && <span style={{ color: 'var(--muted)', fontSize: 10 }}> ({f.source_location})</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {row.related_part_numbers && row.related_part_numbers.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11 }}>
              <strong style={{ color: 'var(--muted)' }}>Parts:</strong> {row.related_part_numbers.join(', ')}
            </div>
          )}
          {row.related_vendors && row.related_vendors.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11 }}>
              <strong style={{ color: 'var(--muted)' }}>Vendors:</strong> {row.related_vendors.join(', ')}
            </div>
          )}
          {row.decisions && row.decisions.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11 }}>
              <strong style={{ color: 'var(--muted)' }}>Decisions:</strong>
              <ul style={{ margin: '2px 0 0 18px' }}>{row.decisions.map((dx, i) => <li key={i}>{dx}</li>)}</ul>
            </div>
          )}
          {row.data_quality_flags && row.data_quality_flags.length > 0 && (
            <div style={{ marginBottom: 6, fontSize: 11, color: 'var(--orange)' }}>
              <strong>⚠ Data quality:</strong> {row.data_quality_flags.join(' · ')}
            </div>
          )}
          {row.cost_data && row.cost_data.cost_completeness && row.cost_data.cost_completeness !== 'not_applicable' && (
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>
              <strong>COGS:</strong> {row.cost_data.cost_completeness}
              {row.cost_data.total_cost_usd != null && <> · ${row.cost_data.total_cost_usd.toLocaleString()}</>}
              {row.cost_data.line_count != null && <> · {row.cost_data.line_count} lines</>}
              {row.cost_data.notes && <span> — {row.cost_data.notes}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
