import { useState } from 'react'
import { KpiTargetsPanel } from './KpiTargetsPanel'

/**
 * Reusable "Set targets" launcher for division pages. Drops on each
 * division page header so the lead can edit targets for their KPIs.
 *
 * Joseph (platform owner) sees + edits everything everywhere.
 * Each division lead sees their own division + global, edits only
 * their own. Read-only fallback if anyone else opens the panel.
 *
 * Pass the metrics relevant to the current page so the panel only
 * shows targets for those.
 */
interface Props {
  division: 'cx' | 'marketing' | 'operations' | 'pe' | 'manufacturing' | null
  metrics: string[]
  label?: string
}

export function DivisionTargetsButton({ division, metrics, label }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={`Set / view KPI targets for ${division ?? 'global'}`}
        style={{
          background: 'var(--panel-2)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: 'var(--text)',
          padding: '4px 10px',
          borderRadius: 4,
          fontSize: 11,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        🎯 {label ?? 'Set targets'}
      </button>
      {open && (
        <KpiTargetsPanel metrics={metrics} division={division} onClose={() => setOpen(false)} />
      )}
    </>
  )
}
