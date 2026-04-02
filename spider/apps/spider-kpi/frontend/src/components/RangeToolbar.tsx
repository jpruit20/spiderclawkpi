import { useMemo, useState } from 'react'
import { buildCustomRange, buildPresetRange, dateInputValue, RangePreset, RangeState, summarizeRangeLabel } from '../lib/range'

const PRESETS: { key: RangePreset; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7D' },
  { key: '14d', label: '14D' },
  { key: '30d', label: '30D' },
  { key: '90d', label: '90D' },
]

export function RangeToolbar({
  rows,
  range,
  onChange,
}: {
  rows: { business_date: string }[]
  range: RangeState
  onChange: (range: RangeState) => void
}) {
  const [draftStart, setDraftStart] = useState(range.startDate)
  const [draftEnd, setDraftEnd] = useState(range.endDate)

  const minDate = '2024-01-01'
  const maxDate = useMemo(() => [...rows].sort((a, b) => a.business_date.localeCompare(b.business_date)).at(-1)?.business_date || new Date().toISOString().slice(0, 10), [rows])
  const availableDays = rows.filter((row) => row.business_date >= range.startDate && row.business_date <= range.endDate).length
  const requestedDays = range.startDate && range.endDate ? Math.max(1, Math.round((new Date(`${range.endDate}T00:00:00Z`).getTime() - new Date(`${range.startDate}T00:00:00Z`).getTime()) / 86400000) + 1) : 0

  return (
    <div className="toolbar">
      <div className="range-group">
        {PRESETS.map((preset) => (
          <button
            key={preset.key}
            className={range.preset === preset.key ? 'range-button active' : 'range-button'}
            onClick={() => {
              const next = buildPresetRange(preset.key as Exclude<RangePreset, 'custom'>, rows)
              setDraftStart(next.startDate)
              setDraftEnd(next.endDate)
              onChange(next)
            }}
          >
            {preset.label}
          </button>
        ))}
        <button className={range.preset === 'custom' ? 'range-button active' : 'range-button'} onClick={() => onChange(buildCustomRange(draftStart || minDate, draftEnd || maxDate))}>Custom</button>
      </div>
      <div className="range-custom-wrap">
        <input type="date" value={dateInputValue(draftStart)} min={minDate} max={maxDate} onChange={(e) => setDraftStart(e.target.value)} />
        <span>→</span>
        <input type="date" value={dateInputValue(draftEnd)} min={minDate} max={maxDate} onChange={(e) => setDraftEnd(e.target.value)} />
        <button className="range-button" onClick={() => onChange(buildCustomRange(draftStart || minDate, draftEnd || maxDate))}>Apply</button>
      </div>
      <div className="scope-note">
        Showing: {summarizeRangeLabel(range)}
        {requestedDays > 0 && availableDays < requestedDays ? (
          <>
            <br />
            Showing {availableDays} available days within requested {requestedDays}-day range
          </>
        ) : null}
      </div>
    </div>
  )
}
