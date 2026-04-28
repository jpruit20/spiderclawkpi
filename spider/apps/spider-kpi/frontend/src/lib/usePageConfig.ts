import { useEffect, useState, useCallback, useMemo } from 'react'
import { api } from './api'
import type { PageConfigCardOverride, PageConfigResponse, PageGridLayouts } from './api'

/**
 * usePageConfig — load, mutate, and persist a division's layout
 * configuration. Each lead manages their own division; Joseph
 * manages everyone's. Read-only fallback for everyone else.
 *
 * Usage:
 *   const cfg = usePageConfig('operations')
 *   const ordered = cfg.applyTo([
 *     { id: 'shipping_intelligence', node: <ShippingCard /> },
 *     { id: 'sharepoint_intelligence', node: <SharepointCard /> },
 *   ])
 *
 * cfg.toggleVisibility(id), cfg.rename(id, title), cfg.move(id, dir),
 * cfg.save(summary), cfg.reset(), etc.
 *
 * Auto-saves to /api/page-configs/{division} on save() / debounced
 * after move/rename/toggle. Audit log is appended server-side.
 */

export interface CardItem<T = unknown> {
  id: string
  node: T
  defaultTitle?: string
}

export interface UsePageConfigResult<T = unknown> {
  loading: boolean
  config: PageConfigResponse | null
  canEdit: boolean
  customizeMode: boolean
  setCustomizeMode: (v: boolean) => void
  applyTo: (items: CardItem<T>[]) => Array<CardItem<T> & { override: PageConfigCardOverride; visible: boolean; title: string | undefined }>
  isVisible: (id: string) => boolean
  cardTitle: (id: string, fallback: string) => string
  toggleVisibility: (id: string) => void
  rename: (id: string, title: string | null) => void
  move: (id: string, direction: 'up' | 'down' | number) => void
  save: (summary?: string) => Promise<void>
  reset: () => Promise<void>
  dirty: boolean
  /** Saved per-breakpoint grid layout (drag/resize). null if user hasn't customized yet. */
  gridLayouts: PageGridLayouts | null
  /** Replace the in-memory grid layouts (call from RGL onLayoutChange). */
  setGridLayouts: (next: PageGridLayouts) => void
}

export function usePageConfig<T = unknown>(division: string): UsePageConfigResult<T> {
  const [config, setConfig] = useState<PageConfigResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [customizeMode, setCustomizeMode] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [overrides, setOverrides] = useState<Record<string, PageConfigCardOverride>>({})
  const [gridLayouts, setGridLayoutsState] = useState<PageGridLayouts | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.pageConfigGet(division, ctl.signal)
      .then(c => {
        setConfig(c)
        setOverrides({ ...(c.config_json?.card_overrides || {}) })
        setGridLayoutsState(c.config_json?.grid_layout ?? null)
        setDirty(false)
      })
      .catch(() => undefined)
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [division])

  const setGridLayouts = useCallback((next: PageGridLayouts) => {
    setGridLayoutsState(next)
    setDirty(true)
  }, [])

  const isVisible = useCallback((id: string) => {
    const ov = overrides[id]
    if (ov?.visible === false) return false
    return true
  }, [overrides])

  const cardTitle = useCallback((id: string, fallback: string) => {
    const ov = overrides[id]
    return ov?.title || fallback
  }, [overrides])

  const applyTo = useCallback((items: CardItem<T>[]) => {
    return items
      .map((it, defaultOrder) => {
        const override = overrides[it.id] || {}
        return {
          ...it,
          override,
          visible: override.visible !== false,
          title: override.title ?? undefined,
          _order: override.order ?? defaultOrder,
        }
      })
      .sort((a, b) => (a._order as number) - (b._order as number))
  }, [overrides])

  const toggleVisibility = useCallback((id: string) => {
    setOverrides(o => ({
      ...o,
      [id]: { ...(o[id] || {}), visible: !(o[id]?.visible !== false ? true : false) },
    }))
    setDirty(true)
  }, [])

  const rename = useCallback((id: string, title: string | null) => {
    setOverrides(o => ({ ...o, [id]: { ...(o[id] || {}), title } }))
    setDirty(true)
  }, [])

  const move = useCallback((id: string, direction: 'up' | 'down' | number) => {
    setOverrides(o => {
      // Find current order. If not set, infer position from a stable
      // ordering of all currently-known ids.
      const allIds = Object.keys(o).length > 0 ? Object.keys(o) : [id]
      const current = o[id]?.order ?? allIds.indexOf(id)
      let newOrder: number
      if (direction === 'up') newOrder = current - 1
      else if (direction === 'down') newOrder = current + 1
      else newOrder = direction
      return {
        ...o,
        [id]: { ...(o[id] || {}), order: newOrder },
      }
    })
    setDirty(true)
  }, [])

  const save = useCallback(async (summary?: string) => {
    if (!config) return
    const next = {
      ...(config.config_json || {}),
      card_overrides: overrides,
      grid_layout: gridLayouts ?? undefined,
    }
    const updated = await api.pageConfigUpsert(division, next, summary)
    setConfig(updated)
    setDirty(false)
  }, [config, overrides, gridLayouts, division])

  const reset = useCallback(async () => {
    await api.pageConfigReset(division)
    setOverrides({})
    setGridLayoutsState(null)
    setDirty(false)
    // Re-fetch the cleared row
    const c = await api.pageConfigGet(division)
    setConfig(c)
  }, [division])

  return {
    loading,
    config,
    canEdit: config?.can_edit ?? false,
    customizeMode,
    setCustomizeMode,
    applyTo,
    isVisible,
    cardTitle,
    toggleVisibility,
    rename,
    move,
    save,
    reset,
    dirty,
    gridLayouts,
    setGridLayouts,
  }
}
