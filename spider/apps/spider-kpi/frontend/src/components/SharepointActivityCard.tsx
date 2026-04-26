import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { SharepointRecentChanges } from '../lib/api'
import { SourceFreshnessChip } from './SourceFreshnessChip'

/**
 * SharePoint activity feed scoped to a dashboard division.
 *
 * Drops on PE / Operations / Manufacturing pages with a ``division``
 * prop matching the connector's folder→division mapping
 * (Engineering → pe, Production and QC → manufacturing,
 * Project Management → operations).
 *
 * Shows the last 7 days of recent file changes per product, joined
 * with structured list items (ECRs, vendor specs, master trackers).
 * Each row is clickable into the live SharePoint URL.
 */

interface Props {
  division: 'pe' | 'operations' | 'manufacturing'
  windowDays?: number
}

const DIVISION_LABEL: Record<Props['division'], string> = {
  pe: 'Engineering activity',
  operations: 'Project Management activity',
  manufacturing: 'Production & QC activity',
}

const DIVISION_FOLDER: Record<Props['division'], string> = {
  pe: 'Engineering',
  operations: 'Project Management',
  manufacturing: 'Production and QC',
}

function relative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const secs = (Date.now() - new Date(iso).getTime()) / 1000
  if (secs < 60) return 'just now'
  const m = Math.floor(secs / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function fileIcon(mime: string | null): string {
  if (!mime) return '📄'
  if (mime.startsWith('image/')) return '🖼'
  if (mime.startsWith('video/')) return '🎬'
  if (mime.includes('pdf')) return '📕'
  if (mime.includes('spreadsheet') || mime.includes('excel')) return '📊'
  if (mime.includes('wordprocessing') || mime.includes('msword')) return '📝'
  if (mime.includes('presentation') || mime.includes('powerpoint')) return '📽'
  if (mime.includes('zip') || mime.includes('compressed')) return '📦'
  return '📄'
}

function fmtSize(bytes: number | null): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}GB`
}

export function SharepointActivityCard({ division, windowDays = 7 }: Props) {
  const [data, setData] = useState<SharepointRecentChanges | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [productFilter, setProductFilter] = useState<string>('all')

  useEffect(() => {
    const ctl = new AbortController()
    api.sharepointRecentChanges(
      {
        division,
        days: windowDays,
        spider_product: productFilter === 'all' ? undefined : productFilter,
        limit: 60,
      },
      ctl.signal,
    )
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [division, windowDays, productFilter])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>{DIVISION_LABEL[division]} (SharePoint)</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>{DIVISION_LABEL[division]} (SharePoint)</strong></div>
        <div className="state-message">Loading SharePoint activity…</div>
      </section>
    )
  }

  const products = Array.from(
    new Set([
      ...data.documents.map(d => d.spider_product),
      ...data.list_items.map(li => li.spider_product),
    ].filter((x): x is string => Boolean(x)))
  ).sort()

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <strong>{DIVISION_LABEL[division]} (SharePoint · AMW)</strong>
            <SourceFreshnessChip source="sharepoint" label="SP" />
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Recent changes from the <code>{DIVISION_FOLDER[division]}</code> folder across the 5 Spider product cards.
            Last {windowDays} days · {data.documents.length} files · {data.list_items.length} list items.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: 360, justifyContent: 'flex-end' }}>
          {['all', ...products].map(p => (
            <button
              key={p}
              onClick={() => setProductFilter(p)}
              style={{
                padding: '4px 10px',
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.1)',
                background: productFilter === p ? 'var(--blue)' : 'var(--panel-2)',
                color: productFilter === p ? '#fff' : 'var(--muted)',
                fontSize: 11,
                cursor: 'pointer',
              }}
            >
              {p === 'all' ? 'All products' : p}
            </button>
          ))}
        </div>
      </div>

      {/* Documents */}
      {data.documents.length === 0 ? (
        <div className="state-message" style={{ marginTop: 10 }}>
          No file changes in the last {windowDays} days{productFilter !== 'all' ? ` for ${productFilter}` : ''}.
        </div>
      ) : (
        <div style={{ marginTop: 10, maxHeight: 360, overflowY: 'auto', fontSize: 12 }}>
          {data.documents.map((d, i) => (
            <a
              key={i}
              href={d.web_url ?? '#'}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'grid',
                gridTemplateColumns: '24px 1fr auto auto',
                gap: 8,
                padding: '6px 8px',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                alignItems: 'baseline',
                textDecoration: 'none',
                color: 'var(--text)',
              }}
            >
              <span>{fileIcon(d.mime_type)}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={d.path}>
                <strong>{d.name}</strong>
                <span style={{ color: 'var(--muted)', marginLeft: 6, fontSize: 11 }}>
                  {d.spider_product ? `· ${d.spider_product}` : ''}
                  {d.modified_by_email ? ` · ${d.modified_by_email.split('@')[0]}` : ''}
                </span>
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtSize(d.size_bytes)}</span>
              <span style={{ color: 'var(--muted)', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
                {relative(d.modified_at)}
              </span>
            </a>
          ))}
        </div>
      )}

      {/* List items section if any */}
      {data.list_items.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Structured list updates ({data.list_items.length})
          </div>
          <div style={{ fontSize: 12 }}>
            {data.list_items.map((li, i) => (
              <a
                key={i}
                href={li.web_url ?? '#'}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '4px 8px',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  textDecoration: 'none',
                  color: 'var(--text)',
                }}
              >
                <span>
                  <span style={{ color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, marginRight: 6 }}>
                    {li.list_name}
                  </span>
                  {li.title ?? '(untitled)'}
                  {li.spider_product && (
                    <span style={{ color: 'var(--muted)', marginLeft: 6, fontSize: 11 }}>· {li.spider_product}</span>
                  )}
                </span>
                <span style={{ color: 'var(--muted)', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
                  {relative(li.modified_at)}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
