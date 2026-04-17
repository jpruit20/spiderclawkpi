import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { SlackPulseResponse, SlackChannelSummary } from '../lib/types'
import { formatFreshness, fmtInt } from '../lib/format'

/**
 * Reusable Slack pulse card. Drops on any division page with a channel filter;
 * owns its own load + channel dropdown. Falls back gracefully if Slack isn't
 * configured on the backend yet (empty state with setup instructions).
 */
type Props = {
  title?: string
  subtitle?: string
  /** Default channel name to show (e.g. 'general-news'). The card will pick the matching channel_id from the list. */
  defaultChannelName?: string
  /** Alternative: pass a channel_id directly, skipping the name lookup. */
  defaultChannelId?: string
  days?: number
  showChannelSwitcher?: boolean
}

function sparkline(daily: { message_count: number }[]): string {
  if (!daily.length) return ''
  const max = Math.max(...daily.map(d => d.message_count), 1)
  const blocks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']
  return daily.map(d => blocks[Math.min(blocks.length - 1, Math.floor((d.message_count / max) * (blocks.length - 1)))]).join('')
}

export function SlackPulseCard({
  title = 'Slack pulse',
  subtitle,
  defaultChannelName,
  defaultChannelId,
  days = 14,
  showChannelSwitcher = true,
}: Props) {
  const [channels, setChannels] = useState<SlackChannelSummary[] | null>(null)
  const [channelId, setChannelId] = useState<string | null>(defaultChannelId || null)
  const [data, setData] = useState<SlackPulseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load channels once
  useEffect(() => {
    let cancelled = false
    api.slackChannels()
      .then(r => {
        if (cancelled) return
        setChannels(r.channels)
        if (!channelId && defaultChannelName) {
          const match = r.channels.find(c => c.name === defaultChannelName)
          if (match) setChannelId(match.channel_id)
        }
      })
      .catch(() => { if (!cancelled) setChannels([]) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultChannelName])

  // Load pulse whenever channel changes
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.slackPulse(channelId || undefined, days)
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load Slack pulse') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [channelId, days])

  const sparklineStr = useMemo(() => sparkline(data?.daily || []), [data])
  const notConfigured = data !== null && data.configured === false
  const selectedChannel = data?.channel

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>{title}</strong>
        <span className="venom-panel-hint">
          {selectedChannel ? `#${selectedChannel.name || selectedChannel.channel_id}` : 'All public channels'}
        </span>
      </div>

      {subtitle && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{subtitle}</p>
      )}

      {notConfigured && (
        <div className="state-message warn">
          Slack is not configured on the backend. Add
          <code style={{ margin: '0 4px' }}>SLACK_BOT_TOKEN</code>
          and
          <code style={{ margin: '0 4px' }}>SLACK_SIGNING_SECRET</code>
          to the droplet env and restart the backend.
        </div>
      )}

      {!notConfigured && (
        <>
          {showChannelSwitcher && channels && channels.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <select
                value={channelId || ''}
                onChange={e => setChannelId(e.target.value || null)}
                className="deci-input"
                style={{ fontSize: 12 }}
              >
                <option value="">All public channels</option>
                {channels
                  .filter(c => !c.is_archived)
                  .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
                  .map(c => (
                    <option key={c.channel_id} value={c.channel_id}>
                      {c.is_private ? '🔒' : '#'} {c.name || c.channel_id}
                    </option>
                  ))}
              </select>
            </div>
          )}

          {loading && <div className="state-message">Loading Slack pulse…</div>}
          {error && <div className="state-message error">{error}</div>}

          {!loading && !error && data && (
            <>
              <div className="venom-bar-list" style={{ marginBottom: 10 }}>
                <div className="venom-breakdown-row">
                  <span className="venom-bar-label">Messages ({data.window.days}d)</span>
                  <span className="venom-breakdown-val">{fmtInt(data.totals.messages)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span className="venom-bar-label">Unique users</span>
                  <span className="venom-breakdown-val">{fmtInt(data.totals.unique_users_seen)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span className="venom-bar-label">Reactions</span>
                  <span className="venom-breakdown-val">{fmtInt(data.totals.reactions)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span className="venom-bar-label">Files shared</span>
                  <span className="venom-breakdown-val">{fmtInt(data.totals.files)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span className="venom-bar-label">Thread replies</span>
                  <span className="venom-breakdown-val">{fmtInt(data.totals.replies)}</span>
                </div>
              </div>

              {sparklineStr && (
                <div style={{ fontFamily: 'monospace', fontSize: 18, letterSpacing: 1, lineHeight: 1 }}>
                  {sparklineStr}
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                    {data.daily[0]?.business_date.slice(5)} → {data.daily[data.daily.length - 1]?.business_date.slice(5)} · msgs/day
                  </div>
                </div>
              )}

              {data.latest_message && (
                <div className="list-item status-muted" style={{ marginTop: 10 }}>
                  <div className="item-head">
                    <strong style={{ fontSize: 12 }}>
                      {data.latest_message.user_name || data.latest_message.user_id || '?'}
                    </strong>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      {data.latest_message.ts_dt ? formatFreshness(data.latest_message.ts_dt) : ''}
                    </span>
                  </div>
                  <p style={{ fontSize: 11 }}>
                    {(data.latest_message.text || '').slice(0, 220)}
                    {data.latest_message.text && data.latest_message.text.length > 220 ? '…' : ''}
                  </p>
                </div>
              )}

              {data.totals.messages === 0 && !loading && (
                <div className="state-message">No activity in this window yet.</div>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}
