import { ReactNode, useCallback, useEffect, useState } from 'react'

/**
 * Progressive-disclosure container: shows a header bar with a chevron
 * + optional right-aligned meta; clicking toggles the body.
 *
 * Persists open/closed state under the URL's ?open=id1,id2 param so a
 * shareable link preserves which sections the user had expanded.
 * Storage key fallback keeps state across reloads even without URL.
 *
 * Default-open is configurable per section. Hero content should pass
 * defaultOpen=false if it's for drill-down detail; initial-visible
 * sections should pass defaultOpen=true.
 */
type Props = {
  id: string
  title: ReactNode
  subtitle?: ReactNode
  meta?: ReactNode            // right-aligned text/badges in the header
  defaultOpen?: boolean
  accentColor?: string        // left border color; default none
  children: ReactNode
  /** Optional density — 'compact' trims header padding for dense stacks. */
  density?: 'normal' | 'compact'
  /**
   * Optional mini-dashboard preview. When the section is COLLAPSED
   * and `preview` is provided, this renders below the header instead
   * of hiding the body entirely — letting users glance at high-level
   * metrics/sparklines/text before deciding to drill in. Pattern:
   * pass a small summary component (KPI tiles, mini-chart, 1–2
   * sentence insight). When expanded, full `children` render.
   *
   * Convention: keep preview content under ~120px tall and avoid
   * heavy per-render computations — the preview renders even when
   * collapsed.
   */
  preview?: ReactNode
}

const STORAGE_PREFIX = 'spider-kpi:collapse:'

function _urlOpenSet(): Set<string> {
  try {
    const params = new URLSearchParams(window.location.search)
    const raw = params.get('open') || ''
    return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
  } catch {
    return new Set()
  }
}

function _syncUrl(id: string, open: boolean) {
  try {
    const params = new URLSearchParams(window.location.search)
    const current = new Set((params.get('open') || '').split(',').map(s => s.trim()).filter(Boolean))
    if (open) current.add(id); else current.delete(id)
    const next = Array.from(current).sort().join(',')
    if (next) params.set('open', next); else params.delete('open')
    const qs = params.toString()
    const url = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`
    window.history.replaceState({}, '', url)
  } catch {
    // ignore — URL sync is best-effort
  }
}

export function CollapsibleSection({
  id,
  title,
  subtitle,
  meta,
  defaultOpen = false,
  accentColor,
  children,
  density = 'normal',
  preview,
}: Props) {
  // Resolve initial state from URL > localStorage > defaultOpen
  const computeInitial = (): boolean => {
    try {
      if (_urlOpenSet().has(id)) return true
      const stored = window.localStorage.getItem(STORAGE_PREFIX + id)
      if (stored === 'true') return true
      if (stored === 'false') return false
    } catch { /* SSR/blocked storage */ }
    return defaultOpen
  }

  const [open, setOpen] = useState<boolean>(computeInitial)

  useEffect(() => {
    try { window.localStorage.setItem(STORAGE_PREFIX + id, String(open)) } catch {}
    _syncUrl(id, open)
  }, [id, open])

  // Listen for programmatic expand/collapse requests from tiles.
  useEffect(() => {
    const handler = (evt: Event) => {
      const detail = (evt as CustomEvent).detail as { id?: string; open?: boolean } | undefined
      if (!detail || detail.id !== id) return
      setOpen(detail.open ?? true)
    }
    window.addEventListener('spider-kpi:collapsible', handler)
    return () => window.removeEventListener('spider-kpi:collapsible', handler)
  }, [id])

  const toggle = useCallback(() => setOpen(x => !x), [])

  const padding = density === 'compact' ? '8px 12px' : '12px 16px'

  return (
    <section
      className="card"
      data-collapsible-id={id}
      style={{
        padding: 0,
        borderLeft: accentColor ? `3px solid ${accentColor}` : undefined,
      }}
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        style={{
          display: 'flex',
          alignItems: 'center',
          width: '100%',
          padding,
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          color: 'inherit',
          font: 'inherit',
        }}
      >
        <span
          style={{
            display: 'inline-block',
            transition: 'transform 120ms ease',
            transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
            marginRight: 10,
            color: 'var(--muted)',
            fontSize: 12,
            lineHeight: 1,
            width: 12,
          }}
        >
          ▶
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{title}</div>
          {subtitle && (
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{subtitle}</div>
          )}
        </div>
        {meta && (
          <div style={{ marginLeft: 12, fontSize: 11, color: 'var(--muted)', flexShrink: 0 }}>
            {meta}
          </div>
        )}
      </button>
      {open ? (
        <div style={{ padding: density === 'compact' ? '0 12px 12px' : '0 16px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          {children}
        </div>
      ) : preview ? (
        // Mini-dashboard preview state: render compact summary so the
        // user can glance at the section's high-level state without
        // expanding. Border + lower padding distinguishes it from the
        // expanded full-content state.
        <div
          style={{
            padding: density === 'compact' ? '0 12px 10px' : '0 16px 12px',
            borderTop: '1px solid rgba(255,255,255,0.04)',
          }}
          role="region"
          aria-label={`${typeof title === 'string' ? title : 'Section'} preview — click header to expand`}
        >
          {preview}
        </div>
      ) : null}
    </section>
  )
}
