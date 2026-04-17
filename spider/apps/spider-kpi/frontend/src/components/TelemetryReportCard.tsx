import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { TelemetryReport } from '../lib/types'

/**
 * Surfaces the latest AI-written comprehensive/monthly telemetry report
 * at the top of the Product Engineering page. Shows title + executive
 * summary + key findings; expands to reveal the full markdown body.
 */
export function TelemetryReportCard({ reportType = 'comprehensive' as const }: { reportType?: 'comprehensive' | 'monthly' }) {
  const [report, setReport] = useState<TelemetryReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.latestTelemetryReport(reportType)
      .then(r => { if (!cancelled && r.ok && r.report) setReport(r.report) })
      .catch(() => { /* silent — absence of report should not break page */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [reportType])

  const bodyHtml = useMemo(() => {
    if (!expanded || !report?.body_markdown) return ''
    return renderMarkdown(report.body_markdown)
  }, [expanded, report?.body_markdown])

  if (loading || !report) return null

  return (
    <section className="card" style={{ borderLeft: '3px solid #b88bff' }}>
      <div className="venom-panel-head">
        <strong>Telemetry analysis — {report.report_type === 'comprehensive' ? 'comprehensive baseline' : 'monthly report'}</strong>
        <span className="venom-panel-hint">{report.window_start} → {report.window_end} · Opus 4.7</span>
      </div>

      <h3 style={{ margin: '6px 0 4px', fontSize: 15 }}>{report.title}</h3>
      <p style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
        {report.summary}
      </p>

      {report.key_findings && report.key_findings.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3, marginBottom: 4 }}>
            Key findings
          </div>
          <div className="stack-list compact">
            {report.key_findings.slice(0, 5).map((f, i) => (
              <div key={i} className={`list-item status-${f.urgency === 'high' ? 'bad' : f.urgency === 'medium' ? 'warn' : 'neutral'}`}>
                <div className="item-head">
                  <strong style={{ fontSize: 12 }}>{f.title}</strong>
                  <div className="inline-badges">
                    <span className={`badge ${f.urgency === 'high' ? 'badge-bad' : f.urgency === 'medium' ? 'badge-warn' : 'badge-muted'}`} style={{ fontSize: 10 }}>
                      {f.urgency}
                    </span>
                    <span className="badge badge-muted" style={{ fontSize: 10 }}>{f.category}</span>
                  </div>
                </div>
                <p style={{ fontSize: 11, margin: '4px 0 0' }}>{f.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 10, display: 'flex', gap: 12, alignItems: 'center' }}>
        <button
          className="analysis-link"
          style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit' }}
          onClick={() => setExpanded(x => !x)}
        >
          {expanded ? '▾ Hide full report' : `▸ Read full report (${report.sections.length} sections)`}
        </button>
        <span style={{ color: 'var(--muted)', fontSize: 11 }}>
          {report.sources_used.length} sources · {Object.keys(report.benchmarks).length} benchmarks · {report.recommendations.length} recommendations
        </span>
      </div>

      {expanded && (
        <div
          className="telemetry-report-body"
          style={{ marginTop: 12, padding: 14, background: 'rgba(255,255,255,0.03)', borderRadius: 6, fontSize: 13, lineHeight: 1.6 }}
          dangerouslySetInnerHTML={{ __html: bodyHtml }}
        />
      )}
    </section>
  )
}


/* Lightweight markdown → HTML with safe escaping. Handles the subset
 * the reports actually use (headings, paragraphs, bullets, tables, bold/italic). */
function renderMarkdown(md: string): string {
  const esc = (s: string) => s
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  const lines = md.split('\n')
  const out: string[] = []
  let inUl = false
  let tableRows: string[] = []
  const closeUl = () => { if (inUl) { out.push('</ul>'); inUl = false } }
  const flushTable = () => {
    if (tableRows.length === 0) return
    const header = tableRows[0].trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim())
    out.push('<table style="border-collapse:collapse;margin:10px 0;font-size:12px;width:100%">')
    out.push('<thead><tr>' + header.map(h => `<th style="border:1px solid rgba(255,255,255,0.12);padding:4px 8px;background:rgba(255,255,255,0.05);text-align:left">${esc(h)}</th>`).join('') + '</tr></thead><tbody>')
    for (const row of tableRows.slice(2)) {
      const cells = row.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim())
      out.push('<tr>' + cells.map(c => `<td style="border:1px solid rgba(255,255,255,0.08);padding:4px 8px">${esc(c)}</td>`).join('') + '</tr>')
    }
    out.push('</tbody></table>')
    tableRows = []
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (/^\s*\|.*\|\s*$/.test(line)) { tableRows.push(line); continue }
    if (tableRows.length) flushTable()
    if (!line.trim()) { closeUl(); out.push(''); continue }
    if (line.startsWith('# ')) { closeUl(); out.push(`<h2 style="margin:16px 0 6px;font-size:18px">${esc(line.slice(2))}</h2>`); continue }
    if (line.startsWith('## ')) { closeUl(); out.push(`<h3 style="margin:14px 0 6px;font-size:15px;border-bottom:1px solid rgba(255,255,255,0.08);padding-bottom:3px">${esc(line.slice(3))}</h3>`); continue }
    if (line.startsWith('### ')) { closeUl(); out.push(`<h4 style="margin:10px 0 4px;font-size:13px">${esc(line.slice(4))}</h4>`); continue }
    if (/^\s*-\s+/.test(line)) {
      if (!inUl) { out.push('<ul style="margin:6px 0;padding-left:20px">'); inUl = true }
      let item = esc(line.replace(/^\s*-\s+/, ''))
      item = item.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>').replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">$1</code>')
      out.push(`<li>${item}</li>`)
      continue
    }
    closeUl()
    let p = esc(line).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>').replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">$1</code>')
    out.push(`<p style="margin:6px 0">${p}</p>`)
  }
  if (tableRows.length) flushTable()
  closeUl()
  return out.join('\n')
}
