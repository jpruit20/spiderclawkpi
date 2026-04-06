export function ActionBlock({ title = 'Recommended Next Actions', items }: { title?: string; items: string[] }) {
  return (
    <div className="card action-card">
      <div className="card-title">{title}</div>
      <div className="stack-list action-list">
        {items.length ? items.map((item, index) => (
          <div className={`list-item ${index === 0 ? 'status-good' : index === 1 ? 'status-warn' : 'status-muted'}`} key={index}>
            <div className="item-head">
              <strong>{index === 0 ? 'Do first' : index === 1 ? 'Do next' : 'Keep in view'}</strong>
              <span className="badge badge-neutral">Priority {index + 1}</span>
            </div>
            <p>{item}</p>
          </div>
        )) : <div className="state-message">No action recommendations generated.</div>}
      </div>
    </div>
  )
}
