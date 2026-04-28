import { ReactNode, useMemo } from 'react'
import { ResponsiveGridLayout, type Layout, type Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import type { UsePageConfigResult } from '../lib/usePageConfig'

/**
 * Editing layer that wraps a page's cards in a draggable + resizable
 * grid. Joseph (platform owner) can edit any division. Division
 * leaders can only edit their own division.
 *
 * View mode: cards render in their saved grid positions; no drag,
 * no resize. Click "Customize" in DivisionPageHeader to flip into
 * edit mode — cards then sprout drag handles + corner resize grips.
 *
 * Layout is persisted via usePageConfig.gridLayouts → /api/page-configs.
 *
 * Usage:
 *   const cfg = usePageConfig('operations')
 *   <GridEditor cfg={cfg} items={[
 *     { id: 'recommendations', node: <RecsCard />, defaultH: 6 },
 *     { id: 'shipping', node: <ShippingCard />, defaultH: 14 },
 *   ]} />
 */
export interface GridEditorItem {
  id: string
  node: ReactNode
  /** Default columns out of cols (defaults to full-width: 12 / lg). */
  defaultW?: number
  /** Default row height units — each unit is ~30px. Defaults to 10 (~300px). */
  defaultH?: number
  /** Minimum w/h while resizing. */
  minW?: number
  minH?: number
}

interface Props {
  cfg: UsePageConfigResult
  items: GridEditorItem[]
}

/** Per-breakpoint columns. Mirrors the framework defaults so layouts
 *  saved on a 12-col desktop reflow into 8-col tablet / 4-col mobile. */
const COLS = { lg: 12, md: 8, sm: 4 } as const
const BREAKPOINTS = { lg: 1200, md: 800, sm: 480 } as const
const ROW_HEIGHT = 30
const DEFAULT_H = 10  // ~300px tall — tunable per card via defaultH
const DEFAULT_W = 12  // full width by default; user resizes to taste

/** Build a sane vertical-stack default layout from item list. */
function buildDefaultLayouts(items: GridEditorItem[]): Layouts {
  let cursor = { lg: 0, md: 0, sm: 0 }
  const lg: Layout[] = []
  const md: Layout[] = []
  const sm: Layout[] = []
  for (const it of items) {
    const h = it.defaultH ?? DEFAULT_H
    const wLg = Math.min(it.defaultW ?? DEFAULT_W, COLS.lg)
    const wMd = Math.min(it.defaultW ?? COLS.md, COLS.md)
    const wSm = COLS.sm
    lg.push({ i: it.id, x: 0, y: cursor.lg, w: wLg, h, minW: it.minW ?? 3, minH: it.minH ?? 3 })
    md.push({ i: it.id, x: 0, y: cursor.md, w: wMd, h, minW: it.minW ?? 3, minH: it.minH ?? 3 })
    sm.push({ i: it.id, x: 0, y: cursor.sm, w: wSm, h, minW: it.minW ?? 2, minH: it.minH ?? 3 })
    cursor.lg += h
    cursor.md += h
    cursor.sm += h
  }
  return { lg, md, sm }
}

/** Merge saved layouts with defaults, preserving saved positions and
 *  appending any new card ids the user hasn't seen yet. */
function mergeLayouts(items: GridEditorItem[], saved: Layouts | null): Layouts {
  const defaults = buildDefaultLayouts(items)
  if (!saved) return defaults
  const merge = (defaultArr: Layout[], savedArr?: Layout[]): Layout[] => {
    if (!savedArr || savedArr.length === 0) return defaultArr
    const savedById = new Map(savedArr.map(l => [l.i, l]))
    return defaultArr.map(d => {
      const s = savedById.get(d.i)
      return s ? { ...d, ...s } : d
    })
  }
  return {
    lg: merge(defaults.lg, saved.lg as Layout[] | undefined),
    md: merge(defaults.md, saved.md as Layout[] | undefined),
    sm: merge(defaults.sm, saved.sm as Layout[] | undefined),
  }
}

export function GridEditor({ cfg, items }: Props) {
  const editing = cfg.customizeMode
  const layouts = useMemo(
    () => mergeLayouts(items, cfg.gridLayouts as Layouts | null),
    [items, cfg.gridLayouts],
  )

  // In view mode, hide cards the lead chose to hide. In edit mode,
  // show them dimmed so the lead can re-enable them.
  const renderable = items.filter(it => editing || cfg.isVisible(it.id))

  return (
    <ResponsiveGridLayout
      className={`grid-editor${editing ? ' grid-editor--editing' : ''}`}
      layouts={layouts}
      breakpoints={BREAKPOINTS}
      cols={COLS}
      rowHeight={ROW_HEIGHT}
      isDraggable={editing}
      isResizable={editing}
      compactType="vertical"
      preventCollision={false}
      margin={[12, 12]}
      containerPadding={[0, 0]}
      draggableHandle=".grid-editor__handle"
      onLayoutChange={(_current, all) => {
        if (editing) cfg.setGridLayouts(all as unknown as PageGridLayoutsCompat)
      }}
    >
      {renderable.map(it => {
        const visible = cfg.isVisible(it.id)
        return (
          <div
            key={it.id}
            className={`grid-editor__cell${!visible ? ' grid-editor__cell--hidden' : ''}`}
            style={{ opacity: visible ? 1 : 0.4 }}
          >
            {editing ? <GridEditorChrome id={it.id} cfg={cfg} visible={visible} /> : null}
            <div className="grid-editor__body">
              {it.node}
            </div>
          </div>
        )
      })}
    </ResponsiveGridLayout>
  )
}

/** RGL gives us back a `Layouts` shape with extra runtime properties.
 *  The persisted shape is narrower; assign through this alias to satisfy
 *  the hook's setter signature without forcing every layout key to be present. */
type PageGridLayoutsCompat = Parameters<UsePageConfigResult['setGridLayouts']>[0]

/** Per-card chrome shown in edit mode: drag handle, hide/show, rename. */
function GridEditorChrome({
  id,
  cfg,
  visible,
}: {
  id: string
  cfg: UsePageConfigResult
  visible: boolean
}) {
  return (
    <div
      className="grid-editor__handle"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 8px',
        fontSize: 10,
        background: 'rgba(243,156,18,0.12)',
        borderTop: '1px dashed var(--orange)',
        borderLeft: '1px dashed var(--orange)',
        borderRight: '1px dashed var(--orange)',
        borderTopLeftRadius: 4,
        borderTopRightRadius: 4,
        cursor: 'move',
        userSelect: 'none',
      }}
      onMouseDown={(e) => {
        // Don't capture mouse down on the inner buttons.
        if ((e.target as HTMLElement).tagName === 'BUTTON') {
          e.stopPropagation()
        }
      }}
    >
      <span style={{ color: 'var(--orange)', fontWeight: 700, letterSpacing: 0.5 }}>
        ⠿ {id}
      </span>
      <span style={{ flex: 1 }} />
      <button
        onClick={(e) => { e.stopPropagation(); cfg.toggleVisibility(id) }}
        title={visible ? 'Hide this card' : 'Show this card'}
        style={{
          background: visible ? 'var(--panel)' : 'var(--orange)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: visible ? 'var(--muted)' : '#fff',
          fontSize: 10,
          padding: '1px 6px',
          borderRadius: 2,
          cursor: 'pointer',
          fontWeight: 600,
        }}
      >
        {visible ? '👁 hide' : '👁 show'}
      </button>
    </div>
  )
}
