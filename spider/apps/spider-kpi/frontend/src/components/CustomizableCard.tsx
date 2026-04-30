import { ReactNode, useState } from 'react'
import { CollapsibleSection } from './CollapsibleSection'

/**
 * Wraps any card component on a division page so the page-config
 * customize mode can hide/rename/reorder it.
 *
 * Two modes:
 *   * Default (no `collapsible` prop): transparent passthrough when not
 *     in customize mode — no chrome, no overhead. Backward-compatible
 *     with every existing call site.
 *   * `collapsible` opt-in: wraps the children in a CollapsibleSection
 *     so the user can collapse/expand the section. Optional `preview`
 *     slot renders mini-dashboard summary content when collapsed.
 *
 * Usage:
 *   <CustomizableCard
 *     id="shipping_intelligence"
 *     defaultTitle="Shipping intelligence"
 *     cfg={cfg}
 *     collapsible defaultOpen
 *     preview={<MiniSummary />}
 *   >
 *     <ShippingIntelligenceCard ... />
 *   </CustomizableCard>
 */
interface Props {
  id: string
  defaultTitle: string
  cfg: ReturnType<typeof import('../lib/usePageConfig').usePageConfig>
  children: ReactNode
  /**
   * When true, wraps children in a CollapsibleSection in normal
   * (non-customize) mode so users can collapse the section. Default
   * false to preserve backward compatibility with existing usages.
   */
  collapsible?: boolean
  /**
   * Initial open state when `collapsible` is true. Default true so
   * existing dashboards don't suddenly collapse on first paint;
   * pages can pass false for less-important sections to make the
   * landing view denser.
   */
  defaultOpen?: boolean
  /**
   * Subtitle to render in the CollapsibleSection header. Only used
   * when `collapsible` is true.
   */
  subtitle?: ReactNode
  /**
   * Mini-dashboard preview to render when collapsed. Pass a small
   * React node (KPI tiles, sparkline, 1-2 sentence text) — keeps
   * collapsed state useful without being heavy.
   */
  preview?: ReactNode
  /** Optional left-border accent forwarded to CollapsibleSection. */
  accentColor?: string
}

export function CustomizableCard({
  id, defaultTitle, cfg, children,
  collapsible = false, defaultOpen = true, subtitle, preview, accentColor,
}: Props) {
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const visible = cfg.isVisible(id)
  const title = cfg.cardTitle(id, defaultTitle)

  // Hidden + not customizing → render nothing.
  if (!visible && !cfg.customizeMode) return null

  // Visible + not customizing →
  //   collapsible: wrap in CollapsibleSection so user can fold/unfold.
  //   default: transparent passthrough (legacy behavior).
  if (!cfg.customizeMode) {
    if (collapsible) {
      return (
        <CollapsibleSection
          id={`card:${id}`}
          title={title}
          subtitle={subtitle}
          defaultOpen={defaultOpen}
          accentColor={accentColor}
          preview={preview}
        >
          {children}
        </CollapsibleSection>
      )
    }
    return <>{children}</>
  }

  // Customize mode → wrap with action toolbar.
  return (
    <div style={{ position: 'relative', opacity: visible ? 1 : 0.45 }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '4px 8px', fontSize: 10,
          background: 'rgba(243,156,18,0.10)',
          borderTop: '1px dashed var(--orange)',
          borderLeft: '1px dashed var(--orange)',
          borderRight: '1px dashed var(--orange)',
          borderTopLeftRadius: 4, borderTopRightRadius: 4,
        }}
      >
        <span style={{ color: 'var(--orange)', fontWeight: 700, letterSpacing: 0.5 }}>
          🎛 {id}
        </span>
        {!editingTitle ? (
          <>
            <span style={{ color: 'var(--muted)' }}>{title}</span>
            <button
              onClick={() => { setTitleDraft(title); setEditingTitle(true) }}
              title="Rename this card"
              style={{ background: 'none', border: 'none', color: 'var(--blue)', fontSize: 10, cursor: 'pointer', padding: 0 }}
            >
              ✎ rename
            </button>
          </>
        ) : (
          <>
            <input
              value={titleDraft}
              onChange={e => setTitleDraft(e.target.value)}
              autoFocus
              style={{ background: 'var(--panel)', border: '1px solid var(--orange)', color: 'var(--text)', fontSize: 10, padding: '1px 5px', borderRadius: 2 }}
            />
            <button
              onClick={() => { cfg.rename(id, titleDraft || null); setEditingTitle(false) }}
              style={{ background: 'var(--green)', border: 'none', color: '#fff', fontSize: 10, padding: '1px 5px', borderRadius: 2, cursor: 'pointer' }}
            >
              ✓
            </button>
            <button
              onClick={() => { cfg.rename(id, null); setEditingTitle(false) }}
              style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', fontSize: 10, padding: '1px 5px', borderRadius: 2, cursor: 'pointer' }}
            >
              clear
            </button>
            <button
              onClick={() => setEditingTitle(false)}
              style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: 10, padding: 0, cursor: 'pointer' }}
            >
              ✕
            </button>
          </>
        )}
        <span style={{ flex: 1 }} />
        <button
          onClick={() => cfg.move(id, 'up')}
          title="Move up"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', fontSize: 10, padding: '1px 5px', borderRadius: 2, cursor: 'pointer' }}
        >
          ↑
        </button>
        <button
          onClick={() => cfg.move(id, 'down')}
          title="Move down"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', fontSize: 10, padding: '1px 5px', borderRadius: 2, cursor: 'pointer' }}
        >
          ↓
        </button>
        <button
          onClick={() => cfg.toggleVisibility(id)}
          title={visible ? 'Hide this card' : 'Show this card'}
          style={{
            background: visible ? 'var(--panel)' : 'var(--orange)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: visible ? 'var(--muted)' : '#fff',
            fontSize: 10, padding: '1px 6px', borderRadius: 2, cursor: 'pointer', fontWeight: 600,
          }}
        >
          {visible ? '👁 hide' : '👁 show'}
        </button>
      </div>
      <div style={{ border: '1px dashed var(--orange)', borderTop: 'none', borderBottomLeftRadius: 4, borderBottomRightRadius: 4 }}>
        {children}
      </div>
    </div>
  )
}
