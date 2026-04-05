export function ActionBlock({ title = 'Recommended Next Actions', items }: { title?: string; items: string[] }) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="stack-list">
        {items.length ? items.map((item, index) => (
          <div className="list-item status-good" key={index}>
            <p>{item}</p>
          </div>
        )) : <div className="state-message">No action recommendations generated.</div>}
      </div>
    </div>
  )
}
