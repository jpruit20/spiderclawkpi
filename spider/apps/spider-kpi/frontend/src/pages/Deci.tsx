import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { TruthBadge } from '../components/TruthBadge'
import { ApiError, api } from '../lib/api'
import { fmtInt, fmtPct } from '../lib/format'
import type { DeciDecision, DeciOverview, DeciTeamMember, DeciStatus, DeciPriority, DeciDecisionType } from '../lib/types'

type DeciView = 'overview' | 'matrix' | 'detail' | 'department'

const STATUS_LABELS: Record<DeciStatus, string> = { not_started: 'Not Started', in_progress: 'In Progress', blocked: 'Blocked', complete: 'Complete' }
const PRIORITY_LABELS: Record<DeciPriority, string> = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const TYPE_LABELS: Record<DeciDecisionType, string> = { KPI: 'KPI', Project: 'Project', Initiative: 'Initiative', Issue: 'Issue' }
const DEPARTMENTS = ['Marketing', 'Ops', 'Product', 'CX', 'Manufacturing']

function statusColor(s: string) {
  if (s === 'complete') return 'good'
  if (s === 'blocked') return 'bad'
  if (s === 'in_progress') return 'warn'
  return 'muted'
}

function priorityBadge(p: string) {
  if (p === 'critical') return 'badge-bad'
  if (p === 'high') return 'badge-warn'
  return 'badge-muted'
}

function daysSince(dateStr: string | undefined): number {
  if (!dateStr) return 999
  const d = new Date(dateStr)
  return Math.floor((Date.now() - d.getTime()) / 86400000)
}

function formatTimeAgo(dateStr: string | undefined): string {
  if (!dateStr) return 'Never'
  const days = daysSince(dateStr)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days}d ago`
  if (days < 30) return `${Math.floor(days / 7)}w ago`
  return `${Math.floor(days / 30)}mo ago`
}

// ── Main Component ──
export function Deci() {
  const [view, setView] = useState<DeciView>('overview')
  const [overview, setOverview] = useState<DeciOverview | null>(null)
  const [decisions, setDecisions] = useState<DeciDecision[]>([])
  const [team, setTeam] = useState<DeciTeamMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedDept, setSelectedDept] = useState<string>('Marketing')
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterDept, setFilterDept] = useState<string>('')
  const [filterPriority, setFilterPriority] = useState<string>('')

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [o, d, t] = await Promise.all([
        api.deciOverview().catch(() => null),
        api.deciDecisions().catch(() => []),
        api.deciTeam().catch(() => []),
      ])
      setOverview(o)
      setDecisions(d)
      setTeam(t)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load DECI data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadAll() }, [loadAll])

  const openDetail = useCallback((id: string) => {
    setSelectedId(id)
    setView('detail')
  }, [])

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">DECI Decision Framework</h2>
          <p className="venom-subtitle">
            Driver &middot; Executor &middot; Contributor &middot; Informed — operational control for every decision
          </p>
        </div>
      </div>

      {/* View tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        {([['overview', 'Executive Overview'], ['matrix', 'DECI Matrix'], ['department', 'Departments']] as const).map(([v, label]) => (
          <button key={v} className={`range-button${view === v ? ' active' : ''}`} onClick={() => setView(v)}>{label}</button>
        ))}
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading DECI framework...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          {view === 'overview' ? <OverviewView overview={overview} decisions={decisions} team={team} onOpenDetail={openDetail} onReload={loadAll} /> : null}
          {view === 'matrix' ? <MatrixView decisions={decisions} team={team} onOpenDetail={openDetail} onReload={loadAll} filterStatus={filterStatus} setFilterStatus={setFilterStatus} filterDept={filterDept} setFilterDept={setFilterDept} filterPriority={filterPriority} setFilterPriority={setFilterPriority} /> : null}
          {view === 'detail' && selectedId ? <DetailView decisionId={selectedId} team={team} onBack={() => setView('matrix')} onReload={loadAll} /> : null}
          {view === 'detail' && !selectedId ? <div className="state-message">Select a decision from the Matrix view.</div> : null}
          {view === 'department' ? <DepartmentView decisions={decisions} team={team} selectedDept={selectedDept} setSelectedDept={setSelectedDept} onOpenDetail={openDetail} /> : null}
        </>
      ) : null}
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 1: Executive Overview
// ═══════════════════════════════════════════════════════
function OverviewView({ overview, decisions, team, onOpenDetail, onReload }: {
  overview: DeciOverview | null
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  onOpenDetail: (id: string) => void
  onReload: () => void
}) {
  const totalDecisions = decisions.length
  const noDriver = decisions.filter(d => !d.driver_id).length
  const blocked = decisions.filter(d => d.status === 'blocked').length
  const complete = decisions.filter(d => d.status === 'complete').length
  const inProgress = decisions.filter(d => d.status === 'in_progress').length
  const stale = decisions.filter(d => d.status !== 'complete' && daysSince(d.updated_at) > 7).length

  const kpiCards = useMemo<KpiCardDef[]>(() => [
    { label: 'Total Decisions', value: fmtInt(totalDecisions), sub: `${fmtInt(complete)} complete`, truthState: 'canonical' },
    { label: 'No Driver', value: fmtInt(noDriver), sub: noDriver > 0 ? 'Unmanaged!' : 'All assigned', truthState: noDriver > 0 ? 'stale' : 'canonical', delta: noDriver > 0 ? { text: 'Action needed', direction: 'down' as const } : undefined },
    { label: 'Blocked', value: fmtInt(blocked), sub: 'need escalation', truthState: blocked > 0 ? 'stale' : 'canonical' },
    { label: 'Stale (>7d)', value: fmtInt(stale), sub: 'no update', truthState: stale > 0 ? 'stale' : 'canonical' },
  ], [totalDecisions, noDriver, blocked, complete, stale])

  // Critical decisions feed
  const criticalDecisions = useMemo(() =>
    decisions
      .filter(d => d.priority === 'critical' || d.priority === 'high')
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 10)
  , [decisions])

  // Decision bottlenecks
  const bottlenecks = useMemo(() => {
    const items: { id: string; title: string; reason: string; priority: string }[] = []
    for (const d of decisions) {
      if (!d.driver_id && d.status !== 'complete') items.push({ id: d.id, title: d.title, reason: 'No driver assigned', priority: d.priority })
      else if (d.status !== 'complete' && daysSince(d.updated_at) > 7) items.push({ id: d.id, title: d.title, reason: `Stale: ${formatTimeAgo(d.updated_at)}`, priority: d.priority })
      if (d.contributors.length > 5) items.push({ id: d.id, title: d.title, reason: `${d.contributors.length} contributors (noise)`, priority: d.priority })
    }
    return items.slice(0, 10)
  }, [decisions])

  // Ownership map
  const ownershipMap = useMemo(() => {
    return team.filter(m => m.active).map(m => {
      const driverCount = decisions.filter(d => d.driver_id === m.id).length
      const executorCount = decisions.filter(d => d.executors.some(e => e.member_id === m.id)).length
      const blockedCount = decisions.filter(d => d.driver_id === m.id && d.status === 'blocked').length
      return { member: m, driverCount, executorCount, blockedCount, total: driverCount + executorCount }
    }).sort((a, b) => b.total - a.total)
  }, [team, decisions])

  // Create new decision
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newType, setNewType] = useState<DeciDecisionType>('Project')
  const [newPriority, setNewPriority] = useState<DeciPriority>('medium')
  const [newDept, setNewDept] = useState('')
  const [newDriverId, setNewDriverId] = useState<number | ''>('')
  const [creating, setCreating] = useState(false)

  async function handleCreate() {
    if (!newTitle.trim()) return
    setCreating(true)
    try {
      await api.deciCreateDecision({
        title: newTitle.trim(),
        type: newType,
        priority: newPriority,
        department: newDept || undefined,
        driver_id: newDriverId || undefined,
      })
      setNewTitle('')
      setShowCreate(false)
      onReload()
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      <VenomKpiStrip cards={kpiCards} />

      {/* Create Decision */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Quick Actions</strong>
          <button className="range-button active" onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? 'Cancel' : '+ New Decision'}
          </button>
        </div>
        {showCreate ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', padding: '8px 0' }}>
            <div style={{ flex: '1 1 200px' }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Title</label>
              <input type="text" value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="Decision title..." style={{ width: '100%' }} className="deci-input" />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Type</label>
              <select value={newType} onChange={e => setNewType(e.target.value as DeciDecisionType)} className="deci-input">
                {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Priority</label>
              <select value={newPriority} onChange={e => setNewPriority(e.target.value as DeciPriority)} className="deci-input">
                {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Department</label>
              <select value={newDept} onChange={e => setNewDept(e.target.value)} className="deci-input">
                <option value="">—</option>
                {DEPARTMENTS.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Driver</label>
              <select value={newDriverId} onChange={e => setNewDriverId(e.target.value ? Number(e.target.value) : '')} className="deci-input">
                <option value="">— None —</option>
                {team.filter(m => m.active).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </div>
            <button className="range-button active" onClick={handleCreate} disabled={creating || !newTitle.trim()}>
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        ) : null}
      </section>

      {/* Decision Bottleneck Panel */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Decision Bottlenecks</strong>
          <span className="venom-panel-hint">{bottlenecks.length} issues found</span>
        </div>
        {bottlenecks.length > 0 ? (
          <div className="stack-list compact">
            {bottlenecks.map((b, i) => (
              <div key={`${b.id}-${i}`} className={`list-item status-bad`} style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(b.id)}>
                <div className="item-head">
                  <strong>{b.title}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-bad">{b.reason}</span>
                    <span className={`badge ${priorityBadge(b.priority)}`}>{b.priority}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="state-message" style={{ color: 'var(--green)' }}>No bottlenecks detected. All decisions are properly managed.</div>}
      </section>

      {/* Ownership Map + Critical Feed */}
      <div className="two-col two-col-equal">
        <section className="card">
          <div className="venom-panel-head">
            <strong>Ownership Map</strong>
            <span className="venom-panel-hint">Load per person</span>
          </div>
          {ownershipMap.length > 0 ? (
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Person</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Driving</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Executing</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Blocked</th>
                </tr>
              </thead>
              <tbody>
                {ownershipMap.map(o => (
                  <tr key={o.member.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 500 }}>
                      {o.member.name}
                      {o.member.role ? <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 6 }}>{o.member.role}</span> : null}
                    </td>
                    <td style={{ textAlign: 'right', padding: '6px 8px' }}>{o.driverCount}</td>
                    <td style={{ textAlign: 'right', padding: '6px 8px' }}>{o.executorCount}</td>
                    <td style={{ textAlign: 'right', padding: '6px 8px', color: o.blockedCount > 0 ? 'var(--red)' : undefined }}>{o.blockedCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="state-message">Add team members to see the ownership map.</div>}
        </section>

        <section className="card">
          <div className="venom-panel-head">
            <strong>Critical Decisions Feed</strong>
            <span className="venom-panel-hint">High + Critical priority</span>
          </div>
          {criticalDecisions.length > 0 ? (
            <div className="stack-list compact">
              {criticalDecisions.map(d => (
                <div key={d.id} className={`list-item status-${statusColor(d.status)}`} style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                  <div className="item-head">
                    <strong>{d.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                      <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus] || d.status}</span>
                    </div>
                  </div>
                  <div className="venom-mention-meta">
                    <span className="badge badge-neutral">D: {d.driver_name || 'NONE'}</span>
                    <span className="badge badge-muted">{formatTimeAgo(d.updated_at)}</span>
                    {d.department ? <span className="badge badge-muted">{d.department}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="state-message">No high/critical decisions. Create decisions and assign priority levels.</div>}
        </section>
      </div>

      {/* Velocity Metrics */}
      {overview?.velocity ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Decision Velocity</strong>
            <TruthBadge state="estimated" />
          </div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <div className="mini-stat">
              <span className="mini-stat-value">{overview.velocity.avg_creation_to_decision_hours != null ? `${Math.round(overview.velocity.avg_creation_to_decision_hours)}h` : '—'}</span>
              <span className="mini-stat-label">Avg Creation to Decision</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{overview.velocity.avg_decision_to_complete_hours != null ? `${Math.round(overview.velocity.avg_decision_to_complete_hours)}h` : '—'}</span>
              <span className="mini-stat-label">Avg Decision to Complete</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{fmtInt(overview.velocity.total_decisions)}</span>
              <span className="mini-stat-label">Total Decisions</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{fmtInt(overview.velocity.completed_decisions)}</span>
              <span className="mini-stat-label">Completed</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{overview.velocity.total_decisions > 0 ? fmtPct(overview.velocity.completed_decisions / overview.velocity.total_decisions) : '—'}</span>
              <span className="mini-stat-label">Completion Rate</span>
            </div>
          </div>
        </section>
      ) : null}
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 2: DECI Matrix
// ═══════════════════════════════════════════════════════
function MatrixView({ decisions, team, onOpenDetail, onReload, filterStatus, setFilterStatus, filterDept, setFilterDept, filterPriority, setFilterPriority }: {
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  onOpenDetail: (id: string) => void
  onReload: () => void
  filterStatus: string; setFilterStatus: (s: string) => void
  filterDept: string; setFilterDept: (s: string) => void
  filterPriority: string; setFilterPriority: (s: string) => void
}) {
  const filtered = useMemo(() => {
    let result = [...decisions]
    if (filterStatus) result = result.filter(d => d.status === filterStatus)
    if (filterDept) result = result.filter(d => d.department === filterDept)
    if (filterPriority) result = result.filter(d => d.priority === filterPriority)
    return result.sort((a, b) => {
      // Sort by priority (critical first), then by status (blocked first)
      const pOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      const sOrder: Record<string, number> = { blocked: 0, in_progress: 1, not_started: 2, complete: 3 }
      const pDiff = (pOrder[a.priority] ?? 9) - (pOrder[b.priority] ?? 9)
      if (pDiff !== 0) return pDiff
      return (sOrder[a.status] ?? 9) - (sOrder[b.status] ?? 9)
    })
  }, [decisions, filterStatus, filterDept, filterPriority])

  return (
    <>
      <section className="card">
        <div className="venom-panel-head">
          <strong>DECI Matrix</strong>
          <span className="venom-panel-hint">{filtered.length} of {decisions.length} decisions</span>
        </div>
        {/* Filters */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="deci-input">
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={filterDept} onChange={e => setFilterDept(e.target.value)} className="deci-input">
            <option value="">All departments</option>
            {DEPARTMENTS.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          <select value={filterPriority} onChange={e => setFilterPriority(e.target.value)} className="deci-input">
            <option value="">All priorities</option>
            {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>

        {filtered.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 700 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Decision</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Driver</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Executors</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Contributors</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Status</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Priority</th>
                  <th style={{ textAlign: 'right', padding: '8px' }}>Updated</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(d => {
                  const isStale = d.status !== 'complete' && daysSince(d.updated_at) > 7
                  const noDriver = !d.driver_id
                  const noExecutor = d.executors.length === 0 && d.status === 'in_progress'
                  const rowStyle: React.CSSProperties = {
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    cursor: 'pointer',
                    background: noDriver ? 'rgba(255,80,80,0.08)' : noExecutor ? 'rgba(255,160,80,0.08)' : isStale ? 'rgba(255,200,80,0.06)' : undefined,
                  }
                  return (
                    <tr key={d.id} style={rowStyle} onClick={() => onOpenDetail(d.id)}>
                      <td style={{ padding: '8px', fontWeight: 500 }}>
                        {d.title}
                        {d.department ? <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 6 }}>{d.department}</span> : null}
                      </td>
                      <td style={{ padding: '8px', color: noDriver ? 'var(--red)' : undefined, fontWeight: noDriver ? 700 : 400 }}>
                        {d.driver_name || (noDriver ? 'MISSING' : '—')}
                      </td>
                      <td style={{ padding: '8px' }}>
                        {d.executors.length > 0 ? d.executors.map(e => e.member_name).join(', ') : <span style={{ color: noExecutor ? 'var(--orange)' : 'var(--muted)' }}>{noExecutor ? 'MISSING' : '—'}</span>}
                      </td>
                      <td style={{ padding: '8px', color: d.contributors.length > 5 ? 'var(--orange)' : undefined }}>
                        {d.contributors.length > 0 ? `${d.contributors.length} people` : '—'}
                      </td>
                      <td style={{ textAlign: 'center', padding: '8px' }}>
                        <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus] || d.status}</span>
                      </td>
                      <td style={{ textAlign: 'center', padding: '8px' }}>
                        <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px', color: isStale ? 'var(--orange)' : 'var(--muted)' }}>
                        {formatTimeAgo(d.updated_at)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : <div className="state-message">No decisions match these filters. Create a new decision from the Executive Overview.</div>}
      </section>
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 3: Decision Detail
// ═══════════════════════════════════════════════════════
function DetailView({ decisionId, team, onBack, onReload }: {
  decisionId: string
  team: DeciTeamMember[]
  onBack: () => void
  onReload: () => void
}) {
  const [decision, setDecision] = useState<DeciDecision | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Inline edit state
  const [editStatus, setEditStatus] = useState<DeciStatus>('not_started')
  const [editPriority, setEditPriority] = useState<DeciPriority>('medium')
  const [editDriverId, setEditDriverId] = useState<number | ''>('')
  const [editDept, setEditDept] = useState('')

  // Log entry
  const [logText, setLogText] = useState('')
  const [logBy, setLogBy] = useState('')
  const [logNotes, setLogNotes] = useState('')
  const [addingLog, setAddingLog] = useState(false)

  // Role assignment
  const [addRole, setAddRole] = useState<'executor' | 'contributor' | 'informed'>('executor')
  const [addMemberId, setAddMemberId] = useState<number | ''>('')

  const loadDecision = useCallback(async () => {
    setLoading(true)
    try {
      const d = await api.deciDecision(decisionId)
      setDecision(d)
      setEditStatus(d.status)
      setEditPriority(d.priority)
      setEditDriverId(d.driver_id || '')
      setEditDept(d.department || '')
    } finally {
      setLoading(false)
    }
  }, [decisionId])

  useEffect(() => { void loadDecision() }, [loadDecision])

  async function handleSave() {
    if (!decision) return
    setSaving(true)
    try {
      // Validate: can't go to in_progress without driver
      if (editStatus === 'in_progress' && !editDriverId) {
        alert('Cannot set status to In Progress without a Driver assigned.')
        setSaving(false)
        return
      }
      await api.deciUpdateDecision(decision.id, {
        status: editStatus,
        priority: editPriority,
        driver_id: editDriverId || null,
        department: editDept || null,
      })
      await loadDecision()
      onReload()
    } finally {
      setSaving(false)
    }
  }

  async function handleAddLog() {
    if (!decision || !logText.trim() || !logBy.trim()) return
    setAddingLog(true)
    try {
      await api.deciAddLog(decision.id, { decision_text: logText.trim(), made_by: logBy.trim(), notes: logNotes.trim() || undefined })
      setLogText('')
      setLogNotes('')
      await loadDecision()
    } finally {
      setAddingLog(false)
    }
  }

  async function handleAddAssignment() {
    if (!decision || !addMemberId) return
    try {
      const body: Record<string, unknown> = {
        status: decision.status,
        priority: decision.priority,
        driver_id: decision.driver_id,
        department: decision.department,
        [`${addRole}s`]: [...(decision[`${addRole}s` as keyof DeciDecision] as Array<{member_id: number}>|| []).map(a => a.member_id), Number(addMemberId)],
      }
      await api.deciUpdateDecision(decision.id, body)
      setAddMemberId('')
      await loadDecision()
      onReload()
    } catch { /* ignore */ }
  }

  if (loading) return <Card title="Loading"><div className="state-message">Loading decision...</div></Card>
  if (!decision) return <Card title="Not Found"><div className="state-message">Decision not found.</div></Card>

  return (
    <>
      {/* Back button */}
      <div style={{ marginBottom: 8 }}>
        <button className="range-button" onClick={onBack}>&larr; Back to Matrix</button>
      </div>

      {/* Header */}
      <section className="card">
        <div className="venom-panel-head">
          <strong style={{ fontSize: 16 }}>{decision.title}</strong>
          <div className="inline-badges">
            <span className={`badge badge-${statusColor(decision.status)}`}>{STATUS_LABELS[decision.status] || decision.status}</span>
            <span className={`badge ${priorityBadge(decision.priority)}`}>{decision.priority}</span>
            <span className="badge badge-muted">{TYPE_LABELS[decision.type] || decision.type}</span>
          </div>
        </div>
        {decision.description ? <p style={{ color: 'var(--muted)', fontSize: 13, margin: '8px 0 0' }}>{decision.description}</p> : null}
      </section>

      {/* DECI Assignment Block + Edit Controls */}
      <div className="two-col two-col-equal">
        <section className="card">
          <div className="venom-panel-head">
            <strong>DECI Assignments</strong>
          </div>
          {/* Driver */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>D — DRIVER (owns the decision)</div>
            <select value={editDriverId} onChange={e => setEditDriverId(e.target.value ? Number(e.target.value) : '')} className="deci-input" style={{ width: '100%' }}>
              <option value="">— No Driver (RED FLAG) —</option>
              {team.filter(m => m.active).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </div>
          {/* Executors */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>E — EXECUTORS ({decision.executors.length})</div>
            {decision.executors.map(e => (
              <span key={e.id} className="badge badge-good" style={{ marginRight: 4, marginBottom: 4 }}>{e.member_name}</span>
            ))}
            {decision.executors.length === 0 ? <span style={{ fontSize: 12, color: 'var(--orange)' }}>None assigned</span> : null}
          </div>
          {/* Contributors */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>C — CONTRIBUTORS ({decision.contributors.length})</div>
            {decision.contributors.map(c => (
              <span key={c.id} className="badge badge-neutral" style={{ marginRight: 4, marginBottom: 4 }}>{c.member_name}</span>
            ))}
            {decision.contributors.length === 0 ? <span style={{ fontSize: 12, color: 'var(--muted)' }}>None</span> : null}
            {decision.contributors.length > 5 ? <span className="badge badge-warn" style={{ marginLeft: 4 }}>Too many!</span> : null}
          </div>
          {/* Informed */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>I — INFORMED ({decision.informed.length})</div>
            {decision.informed.map(inf => (
              <span key={inf.id} className="badge badge-muted" style={{ marginRight: 4, marginBottom: 4 }}>{inf.member_name}</span>
            ))}
            {decision.informed.length === 0 ? <span style={{ fontSize: 12, color: 'var(--muted)' }}>None</span> : null}
          </div>
          {/* Add assignment */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
            <select value={addRole} onChange={e => setAddRole(e.target.value as typeof addRole)} className="deci-input">
              <option value="executor">Executor</option>
              <option value="contributor">Contributor</option>
              <option value="informed">Informed</option>
            </select>
            <select value={addMemberId} onChange={e => setAddMemberId(e.target.value ? Number(e.target.value) : '')} className="deci-input">
              <option value="">Select person...</option>
              {team.filter(m => m.active).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <button className="range-button active" onClick={handleAddAssignment} disabled={!addMemberId}>Add</button>
          </div>
        </section>

        <section className="card">
          <div className="venom-panel-head">
            <strong>Status & Controls</strong>
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Status</label>
              <select value={editStatus} onChange={e => setEditStatus(e.target.value as DeciStatus)} className="deci-input" style={{ width: '100%' }}>
                {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Priority</label>
              <select value={editPriority} onChange={e => setEditPriority(e.target.value as DeciPriority)} className="deci-input" style={{ width: '100%' }}>
                {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Department</label>
              <select value={editDept} onChange={e => setEditDept(e.target.value)} className="deci-input" style={{ width: '100%' }}>
                <option value="">—</option>
                {DEPARTMENTS.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <button className="range-button active" onClick={handleSave} disabled={saving} style={{ width: '100%', marginTop: 8 }}>
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {/* KPI Links */}
          <div style={{ marginTop: 16, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 6 }}>Linked KPIs</div>
            {decision.kpi_links.map(link => (
              <span key={link.id} className="badge badge-good" style={{ marginRight: 4, marginBottom: 4 }}>{link.kpi_name}</span>
            ))}
            {decision.kpi_links.length === 0 ? <span style={{ fontSize: 12, color: 'var(--muted)' }}>No KPIs linked</span> : null}
          </div>
        </section>
      </div>

      {/* Decision Timeline */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Decision Timeline</strong>
          <span className="venom-panel-hint">{decision.logs.length} entries</span>
        </div>
        {decision.logs.length > 0 ? (
          <div className="stack-list compact">
            {decision.logs.slice().reverse().map(log => (
              <div key={log.id} className="list-item status-muted">
                <div className="item-head">
                  <strong>{log.decision_text}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-neutral">{log.made_by}</span>
                    <span className="badge badge-muted">{formatTimeAgo(log.created_at)}</span>
                  </div>
                </div>
                {log.notes ? <p className="venom-mention-body">{log.notes}</p> : null}
              </div>
            ))}
          </div>
        ) : <div className="state-message">No decisions logged yet. Add the first entry below.</div>}

        {/* Add log entry */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
          <div style={{ flex: '1 1 200px' }}>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Decision / Update</label>
            <input type="text" value={logText} onChange={e => setLogText(e.target.value)} placeholder="What was decided?" className="deci-input" style={{ width: '100%' }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>By</label>
            <select value={logBy} onChange={e => setLogBy(e.target.value)} className="deci-input">
              <option value="">Who?</option>
              {team.filter(m => m.active).map(m => <option key={m.id} value={m.name}>{m.name}</option>)}
            </select>
          </div>
          <div style={{ flex: '0 1 150px' }}>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Notes</label>
            <input type="text" value={logNotes} onChange={e => setLogNotes(e.target.value)} placeholder="Optional" className="deci-input" style={{ width: '100%' }} />
          </div>
          <button className="range-button active" onClick={handleAddLog} disabled={addingLog || !logText.trim() || !logBy}>
            {addingLog ? 'Adding...' : 'Log Decision'}
          </button>
        </div>
      </section>
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 4: Department Dashboards
// ═══════════════════════════════════════════════════════
function DepartmentView({ decisions, team, selectedDept, setSelectedDept, onOpenDetail }: {
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  selectedDept: string
  setSelectedDept: (d: string) => void
  onOpenDetail: (id: string) => void
}) {
  const deptDecisions = useMemo(() =>
    decisions.filter(d => d.department === selectedDept)
      .sort((a, b) => {
        const pOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
        return (pOrder[a.priority] ?? 9) - (pOrder[b.priority] ?? 9)
      })
  , [decisions, selectedDept])

  const active = deptDecisions.filter(d => d.status !== 'complete')
  const complete = deptDecisions.filter(d => d.status === 'complete')
  const blocked = deptDecisions.filter(d => d.status === 'blocked')
  const noDriver = deptDecisions.filter(d => !d.driver_id && d.status !== 'complete')

  // Department member list
  const deptMembers = useMemo(() =>
    team.filter(m => m.active && m.department === selectedDept)
  , [team, selectedDept])

  return (
    <>
      {/* Department selector */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {DEPARTMENTS.map(d => (
          <button key={d} className={`range-button${selectedDept === d ? ' active' : ''}`} onClick={() => setSelectedDept(d)}>{d}</button>
        ))}
      </div>

      {/* Department KPIs */}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 16 }}>
        <div className="mini-stat">
          <span className="mini-stat-value">{fmtInt(deptDecisions.length)}</span>
          <span className="mini-stat-label">Total Decisions</span>
        </div>
        <div className="mini-stat">
          <span className="mini-stat-value">{fmtInt(active.length)}</span>
          <span className="mini-stat-label">Active</span>
        </div>
        <div className="mini-stat">
          <span className="mini-stat-value" style={{ color: blocked.length > 0 ? 'var(--red)' : undefined }}>{fmtInt(blocked.length)}</span>
          <span className="mini-stat-label">Blocked</span>
        </div>
        <div className="mini-stat">
          <span className="mini-stat-value">{fmtInt(complete.length)}</span>
          <span className="mini-stat-label">Complete</span>
        </div>
        <div className="mini-stat">
          <span className="mini-stat-value" style={{ color: noDriver.length > 0 ? 'var(--red)' : undefined }}>{fmtInt(noDriver.length)}</span>
          <span className="mini-stat-label">No Driver</span>
        </div>
      </div>

      {/* Accountability flags */}
      {(noDriver.length > 0 || blocked.length > 0) ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Accountability Flags</strong>
          </div>
          <div className="stack-list compact">
            {noDriver.map(d => (
              <div key={d.id} className="list-item status-bad" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <span className="badge badge-bad">Missing Driver</span>
                </div>
              </div>
            ))}
            {blocked.map(d => (
              <div key={d.id} className="list-item status-bad" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <span className="badge badge-bad">Blocked</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Active Decisions with DECI overlay */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Active Decisions — {selectedDept}</strong>
          <span className="venom-panel-hint">{active.length} items</span>
        </div>
        {active.length > 0 ? (
          <div className="stack-list compact">
            {active.map(d => (
              <div key={d.id} className={`list-item status-${statusColor(d.status)}`} style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <div className="inline-badges">
                    <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                    <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus]}</span>
                  </div>
                </div>
                <div className="venom-mention-meta" style={{ marginTop: 6 }}>
                  <span className="badge badge-neutral" style={{ fontWeight: 600 }}>D: {d.driver_name || 'NONE'}</span>
                  {d.executors.length > 0 ? <span className="badge badge-good">E: {d.executors.map(e => e.member_name).join(', ')}</span> : null}
                  {d.contributors.length > 0 ? <span className="badge badge-muted">C: {d.contributors.length} people</span> : null}
                  <span className="badge badge-muted">{formatTimeAgo(d.updated_at)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="state-message">No active decisions for {selectedDept}. Create one from the Executive Overview.</div>}
      </section>

      {/* Team in this department */}
      {deptMembers.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>{selectedDept} Team</strong>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {deptMembers.map(m => {
              const driving = decisions.filter(d => d.driver_id === m.id).length
              const executing = decisions.filter(d => d.executors.some(e => e.member_id === m.id)).length
              return (
                <div key={m.id} style={{ padding: '8px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: 8, minWidth: 120 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name}</div>
                  {m.role ? <div style={{ fontSize: 11, color: 'var(--muted)' }}>{m.role}</div> : null}
                  <div style={{ fontSize: 11, marginTop: 4 }}>
                    <span style={{ color: 'var(--green)' }}>{driving} driving</span> &middot; <span>{executing} executing</span>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}

      {/* Completed */}
      {complete.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Completed</strong>
            <span className="venom-panel-hint">{complete.length} done</span>
          </div>
          <div className="stack-list compact">
            {complete.slice(0, 5).map(d => (
              <div key={d.id} className="list-item status-good" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <span className="badge badge-good">Complete</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  )
}
