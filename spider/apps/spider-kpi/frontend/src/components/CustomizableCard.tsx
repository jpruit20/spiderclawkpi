import { ReactNode, useState } from 'react'

/**
 * Wraps any card component on a division page so the page-config
 * customize mode can hide/rename/reorder it. When customize mode is
 * off, this is a transparent passthrough — no chrome, no overhead.
 *
 * Usage:
 *   <CustomizableCard
 *     id="shipping_intelligence"
 *     defaultTitle="Shipping intelligence"
 *     cfg={cfg}
 *   >
 *     <ShippingIntelligenceCard ... />
 *   </CustomizableCard>
 */
interface Props {
  id: string
  defaultTitle: string
  cfg: ReturnType<typeof import('../lib/usePageConfig').usePageConfig>
  children: ReactNode
}

export function CustomizableCard({ id, defaultTitle, cfg, children }: Props) {
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const visible = cfg.isVisible(id)
  const title = cfg.cardTitle(id, defaultTitle)

  // Hidden + not customizing → render nothing.
  if (!visible && !cfg.customizeMode) return null

  // Visible + not customizing → transparent passthrough (no chrome).
  if (!cfg.customizeMode) return <>{children}</>

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
