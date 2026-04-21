import { useState } from 'react'
import { motion } from 'framer-motion'
import { ApiError } from '../lib/api'
import { useAuth } from './AuthGate'

export type CacheInfo = {
  key: string
  computed_at: string | null
  duration_ms: number | null
  age_seconds: number | null
  source: string
}

type Props = {
  info?: CacheInfo | null
  /** When set, shows an owner-only "Refresh" button that calls POST /api/admin/cache/rebuild?key=<info.key>. */
  onRefreshed?: () => void
}

const OWNER_EMAIL = 'joseph@spidergrills.com'

function humanAge(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

/**
 * Small right-aligned badge showing when a cached payload was last
 * recomputed. Cards that read from aggregate_cache should render one
 * at the top right of their header so users can tell if the data is
 * fresh (<15 min) vs stale (upstream job missed a run).
 *
 * For the owner, clicking "Refresh" forces a rebuild via the admin API
 * and fires ``onRefreshed`` so the parent can re-fetch.
 */
export function CacheFreshnessBadge({ info, onRefreshed }: Props) {
  const { user } = useAuth()
  const [refreshing, setRefreshing] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!info) return null

  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL
  const age = info.age_seconds ?? 0
  const stale = age > 30 * 60   // >30 min without a refresh = stale
  const veryStale = age > 60 * 60
  const color = veryStale ? '#ef4444' : stale ? '#f59e0b' : '#64748b'

  const handleRefresh = async () => {
    if (!info.key) return
    setRefreshing(true)
    setErr(null)
    try {
      const res = await fetch(`/api/admin/cache/rebuild?key=${encodeURIComponent(info.key)}`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status, '/api/admin/cache/rebuild')
      await res.json()
      onRefreshed?.()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        fontSize: 10,
        color,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
        fontWeight: 500,
      }}
      title={
        `cache key: ${info.key}\n` +
        `computed at: ${info.computed_at}\n` +
        `build cost: ${info.duration_ms ?? '?'}ms\n` +
        `source: ${info.source}`
      }
    >
      <span>
        {info.source === 'live' ? '● live' : '●'} {humanAge(info.age_seconds)}
      </span>
      {isOwner ? (
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          style={{
            fontSize: 9,
            padding: '2px 6px',
            background: 'transparent',
            border: `1px solid ${color}55`,
            borderRadius: 4,
            color,
            cursor: refreshing ? 'wait' : 'pointer',
            letterSpacing: 0.5,
          }}
        >
          {refreshing ? '…' : 'Refresh'}
        </button>
      ) : null}
      {err ? <span style={{ color: '#ef4444' }}>{err}</span> : null}
    </motion.div>
  )
}
