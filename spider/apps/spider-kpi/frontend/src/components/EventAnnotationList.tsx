import { DiagnosticItem, RecommendationItem } from '../lib/types'

function itemRank(tone: string) {
  if (tone === 'bad') return 0
  if (tone === 'warn') return 1
  if (tone === 'good') return 2
  return 3
}

function severityTone(value?: string) {
  if (value === 'high') return 'bad'
  if (value === 'medium') return 'warn'
  if (value === 'low') return 'good'
  return 'neutral'
}

export function EventAnnotationList({ diagnostics = [], recommendations = [], rangeStart, rangeEnd }: { diagnostics?: DiagnosticItem[]; recommendations?: RecommendationItem[]; rangeStart: string; rangeEnd: string }) {
  const items = [
    ...diagnostics
      .filter((item) => item.business_date >= rangeStart && item.business_date <= rangeEnd)
      .slice(0, 4)
      .map((item) => ({
        id: `diag-${item.id}`,
        businessDate: item.business_date,
        title: item.title,
        summary: item.summary,
        tone: severityTone(item.severity),
      })),
    ...recommendations
      .filter((item) => (item.business_date || rangeEnd) >= rangeStart && (item.business_date || rangeEnd) <= rangeEnd)
      .slice(0, 3)
      .map((item) => ({
        id: `rec-${item.id}`,
        businessDate: item.business_date || rangeEnd,
        title: item.title,
        summary: item.recommended_action,
        tone: severityTone(item.severity),
      })),
  ]
    .sort((a, b) => {
      const toneDelta = itemRank(a.tone) - itemRank(b.tone)
      if (toneDelta !== 0) return toneDelta
      return b.businessDate.localeCompare(a.businessDate)
    })

  if (!items.length) return null

  return (
    <div className="stack-list">
      {items.map((item) => (
        <div className={`list-item status-${item.tone}`} key={item.id}>
          <div className="item-head">
            <strong>{item.title}</strong>
            <div className="inline-badges">
              <span className={`badge badge-${item.tone}`}>{item.tone}</span>
              <span className="badge badge-neutral">{item.businessDate}</span>
            </div>
          </div>
          <p>{item.summary}</p>
        </div>
      ))}
    </div>
  )
}
