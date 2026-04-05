import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RangePreset, RangeState } from './range'

const PRESETS = new Set<RangePreset>(['today', '7d', '14d', '30d', '90d', 'custom'])

export function parseRangeFromSearch(searchParams: URLSearchParams): RangeState | null {
  const preset = searchParams.get('range') as RangePreset | null
  const startDate = searchParams.get('start') || ''
  const endDate = searchParams.get('end') || ''
  if (!preset || !PRESETS.has(preset)) return null
  if (!startDate || !endDate) return null
  return { preset, startDate, endDate }
}

export function useUrlRange(range: RangeState, onHydrate: (range: RangeState) => void) {
  const [searchParams, setSearchParams] = useSearchParams()

  const parsed = useMemo(() => parseRangeFromSearch(searchParams), [searchParams])

  useEffect(() => {
    if (parsed) onHydrate(parsed)
    // hydrate once per route load/search change; consumer should guard if needed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed?.preset, parsed?.startDate, parsed?.endDate])

  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    next.set('range', range.preset)
    next.set('start', range.startDate)
    next.set('end', range.endDate)
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
      console.info('[kpi-ui] filter_change', { range })
    }
  }, [range.endDate, range.preset, range.startDate, searchParams, setSearchParams])
}
