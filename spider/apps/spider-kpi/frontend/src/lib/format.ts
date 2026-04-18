export function fmtPct(value?: number | null, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return `${(value * 100).toFixed(digits)}%`
}

export function fmtInt(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export function fmtDecimal(value?: number | null, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return value.toFixed(digits)
}

export function fmtDuration(seconds?: number | null) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '\u2014'
  const totalMinutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60)
    const mins = totalMinutes % 60
    return `${hours}h ${String(mins).padStart(2, '0')}m`
  }
  return `${totalMinutes}m ${String(secs).padStart(2, '0')}s`
}

export function formatFreshness(timestamp?: string | null) {
  if (!timestamp) return 'n/a'
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return 'n/a'
  const ageMinutes = Math.max(0, Math.round((Date.now() - parsed) / 60000))
  if (ageMinutes < 2) return 'just now'
  if (ageMinutes < 60) return `${ageMinutes}m ago`
  const hours = Math.floor(ageMinutes / 60)
  return `${hours}h ago`
}

/** All human-visible timestamps across the dashboard render in US Eastern
 *  time. Data is stored UTC but readers see ET. */
export const DISPLAY_TZ = 'America/New_York'

/** "Apr 18, 6:42 PM" style display — short, US Eastern. */
export function formatDateTimeET(timestamp?: string | Date | null): string {
  if (!timestamp) return '—'
  const d = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-US', {
    timeZone: DISPLAY_TZ,
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
    hour12: true,
  }) + ' ET'
}

/** "Apr 18, 2026" style date-only display, US Eastern. */
export function formatDateET(timestamp?: string | Date | null): string {
  if (!timestamp) return '—'
  const d = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', {
    timeZone: DISPLAY_TZ,
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

/** Today's date string in ET, YYYY-MM-DD. Used for range inputs and
 *  comparisons that operate on business-date values. Replaces unsafe
 *  patterns like `new Date().toISOString().slice(0,10)` which quietly
 *  uses UTC and gives the wrong day for anyone east of Greenwich. */
export function todayET(): string {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: DISPLAY_TZ,
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now)
  const y = parts.find(p => p.type === 'year')?.value || '1970'
  const m = parts.find(p => p.type === 'month')?.value || '01'
  const d = parts.find(p => p.type === 'day')?.value || '01'
  return `${y}-${m}-${d}`
}

/** Add N days to a YYYY-MM-DD string, returning YYYY-MM-DD. Purely
 *  calendar arithmetic — no timezone involvement. */
export function addDays(isoDate: string, delta: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + delta)
  return dt.toISOString().slice(0, 10)
}

export function currency(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

export function deltaPct(current: number, prior: number) {
  if (!prior) return '\u2014'
  const pct = ((current - prior) / prior) * 100
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(1)}%`
}

export function deltaDirection(current: number, prior: number): 'up' | 'down' | 'flat' {
  if (!prior) return 'flat'
  const pct = ((current - prior) / prior) * 100
  if (pct > 1) return 'up'
  if (pct < -1) return 'down'
  return 'flat'
}
