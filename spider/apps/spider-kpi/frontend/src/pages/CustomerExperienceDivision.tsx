import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { CXActionItem, CXMetricItem, CXSnapshotResponse } from '../lib/types'

type ActionStatus = 'open' | 'in_progress' | 'resolved'

function pct(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`
}

function hrs(value: number) {
  return `${value.toFixed(1)}h`
}

function whole(value: number) {
  return `${Math.round(value)}`
}

function statusTone(status: string) {
  if (status === 'red' || status === 'critical') return 'bad'
  if (status === 'yellow' || status === 'high') return 'warn'
  return 'good'
}

function metricValue(metric: CXMetricItem) {
  if (metric.key.includes('time')) return hrs(metric.current)
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.current)
  return whole(metric.current)
}

function metricTarget(metric: CXMetricItem) {
  if (metric.key.includes('time')) return hrs(metric.target)
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.target)
  return whole(metric.target)
}

function priorityScore(item: CXActionItem) {
  const base = item.priority === 'critical' ? 100 : item.priority === 'high' ? 70 : item.priority === 'medium' ? 40 : 20
  return base + (item.escalation_owner ? 20 : 0)
}

function actionDueDate(item: CXActionItem) {
  return item.priority === 'critical' ? `${item.snapshot_timestamp.slice(0, 10)} EOD` : item.priority === 'high' ? '24h' : item.priority === 'medium' ? '48h' : '72h'
}

export function CustomerExperienceDivision() {
  const [snapshot, setSnapshot] = useState<CXSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.cxSnapshot()
        if (cancelled) return
        setSnapshot(payload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load customer experience division')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const headerMetrics = snapshot?.header_metrics || []
  const gridMetrics = snapshot?.grid_metrics || []
  const actions = useMemo(() => [...(snapshot?.actions || [])].sort((a, b) => priorityScore(b) - priorityScore(a)), [snapshot])
  const todayFocus = snapshot?.today_focus || []
  const teamLoad = snapshot?.team_load || []
  const insights = snapshot?.insights || []
  const snapshotTimestamp = snapshot?.snapshot_timestamp || 'n/a'

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Customer Experience</h2>
        <p>Division-first operating page for Jeremiah’s team using one server-evaluated daily snapshot across KPIs, focus, actions, load, and insights.</p>
        <small className="page-meta">API base: {getApiBase()} · snapshot: {snapshotTimestamp}</small>
      </div>
      {loading ? <Card title="Customer Experience"><div className="state-message">Loading customer experience division…</div></Card> : null}
      {error ? <Card title="Customer Experience Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="four-col">
            {headerMetrics.map((metric) => (
              <Card key={metric.key} title={metric.label}>
                <div className="hero-metric hero-metric-sm">{metricValue(metric)}</div>
                <div className="inline-badges">
                  <span className={`badge badge-${statusTone(metric.status)}`}>{metric.status}</span>
                  <span className="badge badge-neutral">owner {metric.owner}</span>
                  {metric.confidence === 'low' ? <span className="badge badge-warn">LOW CONFIDENCE</span> : null}
                </div>
                <small>Target {metricTarget(metric)} · 7d {metric.trend7d.toFixed(1)}% · 30d {metric.trend30d.toFixed(1)}%</small>
              </Card>
            ))}
          </div>

          <Card title="KPI Grid">
            <div className="three-col">
              {gridMetrics.map((metric) => (
                <div className={`list-item status-${statusTone(metric.status)}`} key={metric.key}>
                  <div className="item-head">
                    <strong>{metric.label}</strong>
                    <span className={`badge badge-${statusTone(metric.status)}`}>{metric.status}</span>
                  </div>
                  <p>{metricValue(metric)} vs target {metricTarget(metric)}</p>
                  <small>Owner: {metric.owner} · Last updated: {metric.snapshot_timestamp}</small>
                  <small>7d trend {metric.trend7d.toFixed(1)}% · Consecutive bad days {metric.consecutive_bad_days || 0}</small>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Today Focus">
            <div className="stack-list">
              {todayFocus.map((item) => (
                <div className={`list-item status-${statusTone(item.priority)}`} key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge badge-${statusTone(item.priority)}`}>{item.priority}</span>
                      <span className="badge badge-neutral">{item.status}</span>
                    </div>
                  </div>
                  <p>{item.required_action}</p>
                  <small>Owner: {item.owner}{item.co_owner ? ` · Co-owner: ${item.co_owner}` : ''}{item.escalation_owner ? ` · Escalated: ${item.escalation_owner}` : ''}</small>
                  <small>Due: {actionDueDate(item)} · Trigger: {item.trigger_condition}</small>
                </div>
              ))}
              {!todayFocus.length ? <div className="list-item status-good"><p>No open priority actions from the current daily snapshot.</p></div> : null}
            </div>
          </Card>

          <Card title="Action Queue">
            <div className="stack-list">
              {actions.map((item) => (
                <div className={`list-item status-${statusTone(item.priority)}`} key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge badge-${statusTone(item.priority)}`}>{item.priority}</span>
                      <span className="badge badge-neutral">{item.status}</span>
                    </div>
                  </div>
                  <p>{item.required_action}</p>
                  <small>Dedup key: {item.dedup_key}</small>
                  <small>Owner: {item.owner}{item.co_owner ? ` · Co-owner: ${item.co_owner}` : ''}{item.escalation_owner ? ` · Escalation owner: ${item.escalation_owner}` : ''}</small>
                  <small>Auto-close: {JSON.stringify(item.auto_close_rule)}</small>
                  <small>Evidence: {(item.evidence || []).map((entry) => typeof entry === 'string' ? entry : JSON.stringify(entry)).join(' · ')}</small>
                </div>
              ))}
              {!actions.length ? <div className="list-item status-good"><p>No non-green KPI has met persistence or critical-trigger requirements.</p></div> : null}
            </div>
          </Card>

          <Card title="Team Load + Distribution">
            <div className="three-col">
              {teamLoad.map((rep) => (
                <div className={`list-item status-${rep.share_pct > 50 ? 'bad' : rep.share_pct > 40 ? 'warn' : 'good'}`} key={rep.name}>
                  <div className="item-head"><strong>{rep.name}</strong><span className="badge badge-neutral">share {rep.share_pct.toFixed(1)}%</span></div>
                  <small>Tickets closed/day: {rep.tickets_closed_per_day.toFixed(1)}</small>
                  <small>Active queue size: {rep.active_queue_size}</small>
                  <small>Throughput ratio: {rep.throughput_ratio.toFixed(2)}</small>
                  <small>Avg close time: {rep.avg_close_time.toFixed(1)}h</small>
                  <small>Reopen rate: {rep.reopen_rate.toFixed(1)}%</small>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Root Cause / Insights">
            <div className="stack-list">
              {insights.map((item, idx) => (
                <div className="list-item" key={idx}>
                  <strong>{item.text}</strong>
                  <small>Evidence: {item.evidence.join(' · ')}</small>
                </div>
              ))}
              {!insights.length ? <div className="list-item status-muted"><p>No multi-signal insights triggered from the current snapshot.</p></div> : null}
            </div>
          </Card>

        </>
      ) : null}
    </div>
  )
}
