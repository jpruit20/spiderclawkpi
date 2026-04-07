import { Card } from '../components/Card'
import { getApiBase } from '../lib/api'
import { Link } from 'react-router-dom'

const divisions = [
  {
    title: 'Customer Experience',
    path: '/division/customer-experience',
    owner: 'Jeremiah',
    summary: 'Queue health, workload balance, response speed, reopen risk, and daily action ownership.',
  },
  {
    title: 'Marketing',
    path: '/division/marketing',
    owner: 'Bailey',
    summary: 'Revenue efficiency, funnel performance, friction impact, and this-week marketing actions.',
  },
  {
    title: 'Product / Engineering',
    path: '/division/product-engineering',
    owner: 'Kyle',
    summary: 'Telemetry-linked reliability, continuation improvements, and product issue prioritization.',
  },
  {
    title: 'Operations',
    path: '/division/operations',
    owner: 'Conor',
    summary: 'Throughput, order aging, late-ship risk, bottlenecks, and exception handling.',
  },
  {
    title: 'Production / Manufacturing',
    path: '/division/production-manufacturing',
    owner: 'David',
    summary: 'Output, yield, defects, rework, downtime, and line bottlenecks.',
  },
]

export function DepartmentViews() {
  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Division Index</h2>
        <p>Launcher only. Department summaries have been removed from this page so each division can live on its own route.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      <div className="three-col">
        {divisions.map((division) => (
          <Card key={division.path} title={division.title}>
            <p>{division.summary}</p>
            <small>Owner: {division.owner}</small>
            <div className="stack-list compact" style={{ marginTop: 12 }}>
              <div className="list-item status-muted">
                <Link to={division.path}>Open division page</Link>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
