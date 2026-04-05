export interface MetricProvenanceItem {
  metric: string
  sourceSystem: string
  queryLogic: string
  timeWindow: string
  refreshCadence: string
  transformationLogic: string
  caveats: string
}

export function MetricProvenancePanel({ title = 'Metric Provenance', items }: { title?: string; items: MetricProvenanceItem[] }) {
  return (
    <details className="card provenance-panel">
      <summary>
        <span>{title}</span>
        <small>Expand for source, window, transform, and caveats</small>
      </summary>
      <div className="stack-list">
        {items.map((item) => (
          <div className="list-item" key={item.metric}>
            <strong>{item.metric}</strong>
            <small>Source: {item.sourceSystem}</small>
            <small>Query: {item.queryLogic}</small>
            <small>Window: {item.timeWindow}</small>
            <small>Refresh: {item.refreshCadence}</small>
            <small>Transform: {item.transformationLogic}</small>
            <small>Caveats: {item.caveats}</small>
          </div>
        ))}
      </div>
    </details>
  )
}
