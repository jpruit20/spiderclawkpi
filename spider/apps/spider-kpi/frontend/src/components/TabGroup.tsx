import { ReactNode, useEffect, useState } from 'react'

/**
 * Horizontal tabs with URL persistence. Each tab is a label+key pair.
 * The active tab's content is rendered; others are unmounted to keep
 * data fetching contained (no simultaneous 6-panel loads).
 *
 * Active tab syncs to a URL query param (default: ?tab=<key>) so
 * reloading or sharing the link preserves the view.
 */
export type Tab = {
  key: string
  label: ReactNode
  body: ReactNode
  badge?: ReactNode         // e.g. count pill next to the label
}

type Props = {
  tabs: Tab[]
  defaultKey?: string
  paramName?: string        // default 'tab'
  density?: 'normal' | 'compact'
}

function _readParam(name: string): string | null {
  try { return new URLSearchParams(window.location.search).get(name) } catch { return null }
}

function _writeParam(name: string, value: string | null) {
  try {
    const params = new URLSearchParams(window.location.search)
    if (value) params.set(name, value); else params.delete(name)
    const qs = params.toString()
    const url = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`
    window.history.replaceState({}, '', url)
  } catch {}
}

export function TabGroup({ tabs, defaultKey, paramName = 'tab', density = 'normal' }: Props) {
  const initial = (() => {
    const fromUrl = _readParam(paramName)
    if (fromUrl && tabs.some(t => t.key === fromUrl)) return fromUrl
    return defaultKey || tabs[0]?.key || ''
  })()
  const [active, setActive] = useState<string>(initial)

  useEffect(() => { _writeParam(paramName, active) }, [active, paramName])

  const activeTab = tabs.find(t => t.key === active) || tabs[0]

  const tabButtonPadding = density === 'compact' ? '6px 12px' : '10px 16px'

  return (
    <div>
      <div
        role="tablist"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 4,
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          marginBottom: 14,
        }}
      >
        {tabs.map(tab => {
          const isActive = tab.key === activeTab.key
          return (
            <button
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActive(tab.key)}
              style={{
                padding: tabButtonPadding,
                background: 'none',
                border: 'none',
                borderBottom: `2px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
                color: isActive ? 'var(--text)' : 'var(--muted)',
                cursor: 'pointer',
                font: 'inherit',
                fontWeight: isActive ? 600 : 500,
                fontSize: 13,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                marginBottom: -1,
              }}
            >
              {tab.label}
              {tab.badge != null && (
                <span
                  style={{
                    padding: '1px 7px',
                    borderRadius: 9,
                    background: isActive ? 'var(--accent)' : 'rgba(255,255,255,0.08)',
                    color: isActive ? '#fff' : 'var(--muted)',
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          )
        })}
      </div>
      <div role="tabpanel" aria-labelledby={activeTab.key}>
        {activeTab.body}
      </div>
    </div>
  )
}
