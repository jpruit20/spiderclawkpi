import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { ACTIVE_CONNECTORS, isLiveConnector, isScaffolded, isTruthfullyHealthy } from '../lib/sourceHealth'
import { SourceHealthItem } from '../lib/types'

function statusTone(status: string) {
  switch (status) {
    case 'healthy':
      return 'good'
    case 'failed':
      return 'bad'
    case 'stale':
      return 'warn'
    case 'disabled':
      return 'muted'
    case 'not_configured':
      return 'warn'
    default:
      return 'neutral'
  }
}

function SourceCard({ row }: { row: SourceHealthItem }) {
  const scaffolded = isScaffolded(row)
  const liveConnector = isLiveConnector(row)
  const internalCompute = row.source_type === 'compute'
  const truthfulHealthy = liveConnector && isTruthfullyHealthy(row)
  const displayStatus = truthfulHealthy ? 'healthy' : row.derived_status
  const label = scaffolded ? 'Type: Scaffolded source' : internalCompute ? 'Type: Internal compute' : 'Type: Live connector'
  const summary = scaffolded
    ? 'Scaffolded source intentionally disabled until live ingestion is implemented.'
    : truthfulHealthy
      ? 'Health: Healthy. Recent successful sync exists.'
      : `Health: ${displayStatus.charAt(0).toUpperCase()}${displayStatus.slice(1)}. ${row.status_summary}`

  return (
    <div className={`list-item status-${statusTone(displayStatus)}`}>
      <div className="item-head">
        <strong>{row.source}</strong>
        <div className="inline-badges">
          <span className={`badge ${scaffolded ? 'badge-muted' : internalCompute ? 'badge-neutral' : 'badge-good'}`}>{label}</span>
          <span className={`badge badge-${statusTone(displayStatus)}`}>{displayStatus}</span>
        </div>
      </div>
      <p>{summary}</p>
      <small>
        Latest run: {row.latest_run_status} · Records: {row.latest_records_processed}
        {row.stale_minutes !== undefined && row.stale_minutes !== null ? ` · Freshness lag: ${row.stale_minutes} min` : ''}
      </small>
      {row.last_success_at ? <small>Last success: {row.last_success_at}</small> : null}
      {!truthfulHealthy ? <small>Health status: {displayStatus}</small> : null}
      {row.last_error && !truthfulHealthy ? <small><strong>Last error:</strong> {row.last_error}</small> : null}
    </div>
  )
}

export function SourceHealthPage() {
  const [rows, setRows] = useState<SourceHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)

  async function load(signal?: AbortSignal) {
    const requestId = ++requestIdRef.current
    setLoading(true)
    setError(null)
    try {
      const payload = await api.sourceHealth(signal)
      if (signal?.aborted || requestId !== requestIdRef.current) return
      setRows(payload)
    } catch (err) {
      if (signal?.aborted || requestId !== requestIdRef.current) return
      if (!signal?.aborted) setError(err instanceof ApiError ? err.message : 'Failed to load source health')
    } finally {
      if (signal?.aborted || requestId !== requestIdRef.current) return
      if (!signal?.aborted) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => {
      controller.abort()
      requestIdRef.current += 1
    }
  }, [])

  const liveConnectors = useMemo(() => rows.filter((row) => isLiveConnector(row)), [rows])
  const scaffoldedRows = useMemo(() => rows.filter((row) => isScaffolded(row)), [rows])
  const computeRows = useMemo(() => rows.filter((row) => row.source_type === 'compute'), [rows])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Source Health</h2>
        <p>Live connectors, scaffolded sources, and internal compute are separated so the UI matches actual system state.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Source Health Status"><div className="state-message">Loading live source health…</div></Card> : null}
      {error ? <Card title="Source Health Error"><div className="state-message error">{error}</div><button className="button" onClick={() => void load()}>Retry</button></Card> : null}
      {!loading && !error ? (
        <>
          <Card title="Live Connectors">
            <div className="stack-list">
              {liveConnectors.map((row) => <SourceCard key={row.source} row={row} />)}
              {!liveConnectors.length ? <div className="state-message">No live connector rows returned.</div> : null}
            </div>
          </Card>
          <div className="two-col">
            <Card title="Scaffolded Sources">
              <div className="stack-list">
                {scaffoldedRows.map((row) => <SourceCard key={row.source} row={row} />)}
                {!scaffoldedRows.length ? <div className="state-message">No scaffolded rows returned.</div> : null}
              </div>
            </Card>
            <Card title="Internal Compute">
              <div className="stack-list">
                {computeRows.map((row) => <SourceCard key={row.source} row={row} />)}
                {!computeRows.length ? <div className="state-message">No compute rows returned.</div> : null}
              </div>
            </Card>
          </div>
          <Card title="Raw Source Health Table">
            {rows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Type</th>
                      <th>Configured</th>
                      <th>Enabled</th>
                      <th>Run Status</th>
                      <th>Derived</th>
                      <th>Blocks Connector Health</th>
                      <th>Last Success</th>
                      <th>Records</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.source}>
                        <td>{row.source}</td>
                        <td>{row.source_type || 'connector'}</td>
                        <td>{String(row.configured)}</td>
                        <td>{String(row.enabled)}</td>
                        <td>{row.latest_run_status}</td>
                        <td>{isLiveConnector(row) && isTruthfullyHealthy(row) ? 'healthy' : row.derived_status}</td>
                        <td>{String(row.blocks_connector_health ?? true)}</td>
                        <td>{row.last_success_at || '—'}</td>
                        <td>{row.latest_records_processed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="state-message">No source health rows returned.</div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  )
}
