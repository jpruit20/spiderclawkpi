import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { SourceHealthItem } from '../lib/types'

/**
 * Tiny "is this connector fresh right now" chip. Drops on any card
 * that renders data sourced from a single connector so the user
 * doesn't have to leave the page to check System Health.
 *
 *   <SourceFreshnessChip source="sharepoint" />
 *   <SourceFreshnessChip source="klaviyo" label="Klaviyo" />
 *
 * Pulls /api/source-health once on mount and finds the matching row.
 * Renders `· source · status · age` in the same muted styling used by
 * the rest of the dashboard so it visually disappears when healthy
 * and stands out when stale/failed.
 */

interface Props {
  source: string
  label?: string
}

const STATUS_COLOR: Record<string, string> = {
  healthy: 'var(--green)',
  stale: 'var(--orange)',
  failed: 'var(--red)',
  degraded: 'var(--orange)',
  running: 'var(--blue)',
  disabled: 'var(--muted)',
  not_configured: 'var(--muted)',
  never_run: 'var(--muted)',
}

function ageLabel(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const ms = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(ms)) return 'never'
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export function SourceFreshnessChip({ source, label }: Props) {
  const [row, setRow] = useState<SourceHealthItem | null>(null)
  const [error, setError] = useState<boolean>(false)

  useEffect(() => {
    const ctl = new AbortController()
    api.sourceHealth(ctl.signal)
      .then(rows => {
        const match = rows.find(r => r.source === source)
        setRow(match ?? null)
      })
      .catch(err => { if (err.name !== 'AbortError') setError(true) })
    return () => ctl.abort()
  }, [source])

  if (error || !row) return null

  // Derived status already factors in stale-threshold + last_error
  const status = row.derived_status
  const color = STATUS_COLOR[status] || 'var(--muted)'
  const display = label || row.source

  return (
    <span
      title={
        `${row.source} · status: ${status}\n`
        + `last success: ${row.last_success_at || '—'}\n`
        + `last run: ${row.latest_run_status} (${row.latest_records_processed} records)`
        + (row.last_error ? `\nlast error: ${row.last_error}` : '')
      }
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '1px 6px',
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: 0.3,
        textTransform: 'uppercase',
        background: 'var(--panel-2)',
        color,
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: color,
        }}
      />
      {display} · {ageLabel(row.last_success_at)}
    </span>
  )
}
