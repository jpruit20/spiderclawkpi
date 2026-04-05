import { CompareMode } from '../lib/compare'

const OPTIONS: Array<{ key: CompareMode; label: string }> = [
  { key: 'prior_period', label: 'Vs Prior Period' },
  { key: 'same_day_last_week', label: 'Vs Same Day Last Week' },
  { key: 'none', label: 'No Compare' },
]

export function CompareToolbar({ mode, onChange }: { mode: CompareMode; onChange: (mode: CompareMode) => void }) {
  return (
    <div className="compare-toolbar">
      {OPTIONS.map((option) => (
        <button
          key={option.key}
          className={mode === option.key ? 'range-button active' : 'range-button'}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
