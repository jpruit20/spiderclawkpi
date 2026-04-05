import { KPIDaily } from './types'

export type CompareMode = 'prior_period' | 'same_day_last_week' | 'none'

export interface ComparePoint {
  label: string
  current: number
  baseline: number | null
  deltaAbs: number | null
  deltaPct: number | null
  comparable: boolean
}

function pct(current: number, baseline: number) {
  if (!baseline) return null
  return ((current - baseline) / baseline) * 100
}

export function compareValue(current: number, baseline: number | null, label: string): ComparePoint {
  if (baseline == null) {
    return { label, current, baseline: null, deltaAbs: null, deltaPct: null, comparable: false }
  }
  return {
    label,
    current,
    baseline,
    deltaAbs: current - baseline,
    deltaPct: pct(current, baseline),
    comparable: true,
  }
}

export function priorPeriodRows(rows: KPIDaily[], startDate: string, length: number): KPIDaily[] {
  const endIndex = rows.findIndex((row) => row.business_date === startDate)
  if (endIndex <= 0 || !length) return []
  return rows.slice(Math.max(0, endIndex - length), endIndex)
}

export function sameDayLastWeekRows(rows: KPIDaily[], currentRows: KPIDaily[]): KPIDaily[] {
  const map = new Map(rows.map((row) => [row.business_date, row]))
  return currentRows
    .map((row) => {
      const d = new Date(`${row.business_date}T00:00:00Z`)
      d.setUTCDate(d.getUTCDate() - 7)
      const prior = d.toISOString().slice(0, 10)
      return map.get(prior)
    })
    .filter((row): row is KPIDaily => Boolean(row))
}

export function formatDeltaPct(value: number | null) {
  if (value == null) return 'n/a'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}
