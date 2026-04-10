export type TruthState = 'canonical' | 'proxy' | 'estimated' | 'degraded' | 'unavailable'

const CLASS_MAP: Record<TruthState, string> = {
  canonical: 'badge-good',
  proxy: 'badge-venom-proxy',
  estimated: 'badge-warn',
  degraded: 'badge-bad',
  unavailable: 'badge-muted',
}

export function TruthBadge({ state }: { state: TruthState }) {
  return <span className={`badge ${CLASS_MAP[state]}`}>{state}</span>
}
