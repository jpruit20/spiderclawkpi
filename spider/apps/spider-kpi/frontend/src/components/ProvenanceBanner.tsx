import { type TruthState } from './TruthBadge'
import { type SourceHealthItem } from '../lib/types'
import { truthStateFromSource } from '../lib/divisionContract'
import { formatFreshness } from '../lib/format'

function formatAge(minutes?: number) {
  if (minutes == null) return 'unknown'
  if (minutes < 2) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

const STATE_STYLES: Record<TruthState, { bg: string; border: string; color: string; icon: string }> = {
  canonical: { bg: 'rgba(16,185,129,0.08)', border: 'rgba(16,185,129,0.25)', color: '#34d399', icon: '\u2713' },
  proxy:     { bg: 'rgba(59,130,246,0.08)', border: 'rgba(59,130,246,0.25)', color: '#60a5fa', icon: '\u2248' },
  estimated: { bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.25)', color: '#fbbf24', icon: '\u223C' },
  degraded:  { bg: 'rgba(239,68,68,0.08)',  border: 'rgba(239,68,68,0.25)',  color: '#f87171', icon: '\u26A0' },
  unavailable: { bg: 'rgba(107,114,128,0.08)', border: 'rgba(107,114,128,0.25)', color: '#9ca3af', icon: '\u2014' },
}

const STATE_LABELS: Record<TruthState, string> = {
  canonical: 'Data verified',
  proxy: 'Proxy data — useful but incomplete',
  estimated: 'Estimated — modeled or heuristic',
  degraded: 'Degraded — one or more sources unhealthy',
  unavailable: 'Data not available',
}

interface ProvenanceBannerProps {
  /** Required source names to check in sourceHealth */
  requiredSources?: string[]
  /** Source health items from the API */
  sourceHealth?: SourceHealthItem[]
  /** Override truth state (skips auto-derivation from sourceHealth) */
  truthState?: TruthState
  /** "Last updated" timestamp (ISO string) */
  lastUpdated?: string | null
  /** Human-readable scope description, e.g. "30-day rolling window" */
  scope?: string
  /** Optional caveat text */
  caveat?: string
  /** Compact single-line mode (default: false) */
  compact?: boolean
}

export function ProvenanceBanner({
  requiredSources = [],
  sourceHealth = [],
  truthState: overrideTruthState,
  lastUpdated,
  scope,
  caveat,
  compact = false,
}: ProvenanceBannerProps) {
  // Derive truth state from source health if not overridden
  const derivedState = overrideTruthState
    ?? (requiredSources.length && sourceHealth.length
      ? (truthStateFromSource(sourceHealth, requiredSources) as TruthState)
      : 'canonical')
  // Map 'blocked' (from divisionContract) to 'unavailable' for display
  const state: TruthState = (derivedState as string) === 'blocked' ? 'unavailable' : derivedState

  const styles = STATE_STYLES[state]
  const degradedSources = sourceHealth
    .filter(s => requiredSources.includes(s.source) && s.derived_status !== 'healthy')

  if (compact) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        fontSize: 11, color: 'var(--muted)', padding: '4px 0',
      }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: styles.bg, color: styles.color, border: `1px solid ${styles.border}`,
        }}>
          <span>{styles.icon}</span> {state}
        </span>
        {lastUpdated ? <span>Updated {formatFreshness(lastUpdated)}</span> : null}
        {scope ? <span>&middot; {scope}</span> : null}
        {requiredSources.length > 0 ? (
          <span>&middot; Sources: {requiredSources.join(', ')}</span>
        ) : null}
        {degradedSources.length > 0 ? (
          <span style={{ color: '#f87171' }}>
            &middot; {degradedSources.map(s => `${s.source} ${s.derived_status}`).join(', ')}
          </span>
        ) : null}
        {caveat ? <span style={{ fontStyle: 'italic' }}>&middot; {caveat}</span> : null}
      </div>
    )
  }

  return (
    <div style={{
      background: styles.bg,
      border: `1px solid ${styles.border}`,
      borderRadius: 8,
      padding: '8px 14px',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10,
      fontSize: 12,
    }}>
      <span style={{ color: styles.color, fontSize: 14, lineHeight: '18px', flexShrink: 0 }}>{styles.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, color: styles.color }}>{STATE_LABELS[state]}</span>
          {lastUpdated ? (
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>
              &middot; Updated {formatFreshness(lastUpdated)}
            </span>
          ) : null}
          {scope ? (
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>
              &middot; {scope}
            </span>
          ) : null}
        </div>
        {requiredSources.length > 0 ? (
          <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2 }}>
            Sources: {requiredSources.map(s => {
              const health = sourceHealth.find(h => h.source === s)
              if (!health) return <span key={s} style={{ color: '#9ca3af' }}>{s} (missing)</span>
              const isHealthy = health.derived_status === 'healthy'
              return (
                <span key={s} style={{ color: isHealthy ? 'var(--muted)' : '#f87171', marginRight: 4 }}>
                  {s}{!isHealthy ? ` (${health.derived_status}${health.stale_minutes ? ` — ${formatAge(health.stale_minutes)}` : ''})` : ''}
                  {requiredSources.indexOf(s) < requiredSources.length - 1 ? ', ' : ''}
                </span>
              )
            })}
          </div>
        ) : null}
        {caveat ? (
          <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2, fontStyle: 'italic' }}>
            {caveat}
          </div>
        ) : null}
      </div>
    </div>
  )
}
