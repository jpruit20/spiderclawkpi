import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../components/AuthGate'
import { Card } from '../components/Card'
import { DeciDraftsCard } from '../components/DeciDraftsCard'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { TruthBadge } from '../components/TruthBadge'
import { ApiError, api } from '../lib/api'
import { fmtInt, fmtPct } from '../lib/format'
import type {
  DeciDecision, DeciOverview, DeciTeamMember, DeciDomain,
  DeciMatrixResponse,
  DeciStatus, DeciPriority, DeciDecisionType,
  DeciDomainStat, DeciEscalationWarning,
} from '../lib/types'

type DeciView = 'overview' | 'map' | 'decisions' | 'detail' | 'roleload' | 'matrix'

const STATUS_LABELS: Record<DeciStatus, string> = { not_started: 'Not Started', in_progress: 'In Progress', blocked: 'Blocked', complete: 'Complete' }
const PRIORITY_LABELS: Record<DeciPriority, string> = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const TYPE_LABELS: Record<DeciDecisionType, string> = { KPI: 'KPI', Project: 'Project', Initiative: 'Initiative', Issue: 'Issue' }
const DEPARTMENTS = ['Marketing', 'Ops', 'Product', 'CX', 'Manufacturing', 'Engineering']

const DOMAIN_CATEGORY_COLORS: Record<string, string> = {
  product: '#3b82f6',
  manufacturing: '#f59e0b',
  commercial: '#10b981',
  cx: '#8b5cf6',
  engineering: '#06b6d4',
  operations: '#6b7280',
}

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

function escalationBadge(s: string) {
  if (s === 'escalated') return 'badge-bad'
  if (s === 'warning') return 'badge-warn'
  return ''
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

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Main Component ──
export function Deci() {
  const [view, setView] = useState<DeciView>('overview')
  const [overview, setOverview] = useState<DeciOverview | null>(null)
  const [decisions, setDecisions] = useState<DeciDecision[]>([])
  const [team, setTeam] = useState<DeciTeamMember[]>([])
  const [domains, setDomains] = useState<DeciDomain[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterDept, setFilterDept] = useState<string>('')
  const [filterPriority, setFilterPriority] = useState<string>('')
  const [filterDomain, setFilterDomain] = useState<string>('')

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [o, d, t, dom] = await Promise.all([
        api.deciOverview().catch(() => null),
        api.deciDecisions().catch(() => []),
        api.deciTeam().catch(() => []),
        api.deciDomains().catch(() => []),
      ])
      setOverview(o)
      setDecisions(d)
      setTeam(t)
      setDomains(dom)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load DECI data')
    } finally {
      setLoading(false)
    }
  }, [])

  /** Silent reload — refreshes data in background without showing loading state or resetting scroll */
  const silentReload = useCallback(async () => {
    try {
      const [o, d, t, dom] = await Promise.all([
        api.deciOverview().catch(() => null),
        api.deciDecisions().catch(() => []),
        api.deciTeam().catch(() => []),
        api.deciDomains().catch(() => []),
      ])
      setOverview(o)
      setDecisions(d)
      setTeam(t)
      setDomains(dom)
    } catch { /* silent — don't flash error on background refresh */ }
  }, [])

  useEffect(() => { void loadAll() }, [loadAll])

  const openDetail = useCallback((id: string) => {
    setSelectedId(id)
    setView('detail')
  }, [])

  const TAB_ITEMS: [DeciView, string][] = [
    ['overview', 'Executive Overview'],
    ['map', 'Decision Map'],
    ['decisions', 'Active Decisions'],
    ['roleload', 'Role Load'],
    ['matrix', 'Leadership Matrix'],
  ]

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">DECI Decision Operating System</h2>
          <p className="venom-subtitle">
            Driver &middot; Executor &middot; Contributor &middot; Informed — active control layer for every decision at Spider Grills
          </p>
        </div>
      </div>

      {/* View tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        {TAB_ITEMS.map(([v, label]) => (
          <button key={v} className={`range-button${view === v ? ' active' : ''}`} onClick={() => setView(v)}>{label}</button>
        ))}
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading DECI framework...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          {view === 'overview' ? <OverviewView overview={overview} decisions={decisions} team={team} domains={domains} onOpenDetail={openDetail} onReload={silentReload} /> : null}
          {view === 'map' ? <DecisionMapView decisions={decisions} team={team} domains={domains} onOpenDetail={openDetail} onReload={silentReload} /> : null}
          {view === 'decisions' ? <ActiveDecisionsView decisions={decisions} team={team} domains={domains} onOpenDetail={openDetail} onReload={silentReload} filterStatus={filterStatus} setFilterStatus={setFilterStatus} filterDept={filterDept} setFilterDept={setFilterDept} filterPriority={filterPriority} setFilterPriority={setFilterPriority} filterDomain={filterDomain} setFilterDomain={setFilterDomain} /> : null}
          {view === 'detail' && selectedId ? <DetailView decisionId={selectedId} team={team} domains={domains} onBack={() => setView('decisions')} onReload={silentReload} /> : null}
          {view === 'detail' && !selectedId ? <div className="state-message">Select a decision from the Active Decisions view.</div> : null}
          {view === 'roleload' ? <RoleLoadView decisions={decisions} team={team} domains={domains} onOpenDetail={openDetail} /> : null}
          {view === 'matrix' ? <LeadershipMatrixView team={team} domains={domains} decisions={decisions} onOpenDetail={openDetail} onReload={silentReload} /> : null}
        </>
      ) : null}
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 1: Executive Overview
// ═══════════════════════════════════════════════════════
function OverviewView({ overview, decisions, team, domains, onOpenDetail, onReload }: {
  overview: DeciOverview | null
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  domains: DeciDomain[]
  onOpenDetail: (id: string) => void
  onReload: () => void
}) {
  const totalDecisions = decisions.length
  const noDriver = decisions.filter(d => !d.driver_id).length
  const blocked = decisions.filter(d => d.status === 'blocked').length
  const complete = decisions.filter(d => d.status === 'complete').length
  const inProgress = decisions.filter(d => d.status === 'in_progress').length
  const stale = decisions.filter(d => d.status !== 'complete' && daysSince(d.updated_at) > 7).length
  const escalated = decisions.filter(d => d.escalation_status === 'escalated' || d.escalation_status === 'warning').length
  const crossFunctional = decisions.filter(d => d.cross_functional && d.status !== 'complete').length

  const kpiCards = useMemo<KpiCardDef[]>(() => [
    { label: 'Total Decisions', value: fmtInt(totalDecisions), sub: `${fmtInt(inProgress)} active, ${fmtInt(complete)} done`, truthState: 'canonical' },
    { label: 'No Driver', value: fmtInt(noDriver), sub: noDriver > 0 ? 'Governance gap!' : 'All assigned', truthState: noDriver > 0 ? 'stale' : 'canonical', delta: noDriver > 0 ? { text: 'Action needed', direction: 'down' as const } : undefined },
    { label: 'Blocked', value: fmtInt(blocked), sub: 'need escalation', truthState: blocked > 0 ? 'stale' : 'canonical' },
    { label: 'Stale (>7d)', value: fmtInt(stale), sub: 'no update', truthState: stale > 0 ? 'stale' : 'canonical' },
  ], [totalDecisions, noDriver, blocked, complete, inProgress, stale])

  // Escalation warnings from overview
  const escalationWarnings = overview?.escalation_warnings ?? []

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
      if (d.contributors && d.contributors.length > 5) items.push({ id: d.id, title: d.title, reason: `${d.contributors.length} contributors (noise)`, priority: d.priority })
      if (d.escalation_status === 'escalated') items.push({ id: d.id, title: d.title, reason: 'Escalated — needs leadership attention', priority: d.priority })
    }
    return items.slice(0, 10)
  }, [decisions])

  // Ownership map
  const ownershipMap = useMemo(() => {
    return team.filter(m => m.active).map(m => {
      const driverCount = decisions.filter(d => d.driver_id === m.id).length
      const executorCount = decisions.filter(d => d.executors?.some(e => e.member_id === m.id)).length
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
  const [newDomainId, setNewDomainId] = useState<number | ''>('')
  const [newCrossFunctional, setNewCrossFunctional] = useState(false)
  const [newDescription, setNewDescription] = useState('')
  const [newDueDate, setNewDueDate] = useState('')
  const [newClickupListId, setNewClickupListId] = useState('')
  const [clickupLists, setClickupLists] = useState<{ list_id: string; list_name: string | null; space_name: string | null }[]>([])
  const [creating, setCreating] = useState(false)
  const [seeding, setSeeding] = useState(false)

  // Auto-fill from domain
  const selectedDomain = useMemo(() => {
    if (!newDomainId) return null
    return domains.find(d => d.id === newDomainId) ?? null
  }, [newDomainId, domains])

  useEffect(() => {
    if (selectedDomain) {
      if (selectedDomain.default_driver_id) setNewDriverId(selectedDomain.default_driver_id)
    }
  }, [selectedDomain])

  // Load ClickUp lists once the user opens the New Decision form, so the
  // "Also create in ClickUp" dropdown is populated. Silent on failure
  // (ClickUp not configured or no tasks synced yet).
  useEffect(() => {
    if (!showCreate) return
    if (clickupLists.length > 0) return
    let cancelled = false
    api.clickupLists()
      .then((r) => { if (!cancelled) setClickupLists(r.lists || []) })
      .catch(() => { /* silent */ })
    return () => { cancelled = true }
  }, [showCreate])  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleCreate() {
    if (!newTitle.trim()) return
    setCreating(true)
    try {
      const created = await api.deciCreateDecision({
        title: newTitle.trim(),
        description: newDescription.trim() || undefined,
        type: newType,
        priority: newPriority,
        department: newDept || undefined,
        driver_id: newDriverId || undefined,
        domain_id: newDomainId || undefined,
        cross_functional: newCrossFunctional,
        due_date: newDueDate || undefined,
      }) as { id?: string }

      // Optionally mirror into ClickUp. Best-effort — a ClickUp failure does
      // not roll back the decision we just created.
      if (newClickupListId && created?.id) {
        const cuPriority = newPriority === 'critical' ? 1 : newPriority === 'high' ? 2 : newPriority === 'medium' ? 3 : 4
        try {
          await api.clickupDeciSync(created.id, { list_id: newClickupListId, priority: cuPriority })
        } catch (err) {
          console.warn('ClickUp sync failed (decision still created):', err)
        }
      }
      setNewTitle('')
      setNewDescription('')
      setNewDomainId('')
      setNewCrossFunctional(false)
      setNewDueDate('')
      setNewClickupListId('')
      setShowCreate(false)
      onReload()
    } finally {
      setCreating(false)
    }
  }

  async function handleSeedDomains() {
    setSeeding(true)
    try {
      await api.deciSeedDomains()
      onReload()
    } finally {
      setSeeding(false)
    }
  }

  return (
    <>
      <VenomKpiStrip cards={kpiCards} />

      {/* Seed domains if empty */}
      {domains.length === 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Setup Required</strong>
          </div>
          <p style={{ color: 'var(--muted)', fontSize: 13, margin: '4px 0 12px' }}>
            Decision Domains haven't been configured yet. Seed the 12 default governance domains to get started.
          </p>
          <button className="range-button active" onClick={handleSeedDomains} disabled={seeding}>
            {seeding ? 'Seeding...' : 'Seed Default Domains'}
          </button>
        </section>
      ) : null}

      {/* Auto-drafted decisions awaiting review (Slack + ClickUp signals) */}
      <DeciDraftsCard onChange={onReload} />

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
            <div style={{ flex: '1 1 100%' }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Description</label>
              <textarea value={newDescription} onChange={e => setNewDescription(e.target.value)} placeholder="What is this decision about? Context, goals, constraints..." rows={2} style={{ width: '100%', resize: 'vertical' }} className="deci-input" />
            </div>
            {domains.length > 0 ? (
              <div>
                <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Domain</label>
                <select value={newDomainId} onChange={e => setNewDomainId(e.target.value ? Number(e.target.value) : '')} className="deci-input">
                  <option value="">— Custom —</option>
                  {domains.filter(d => d.active).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
            ) : null}
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
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Due Date</label>
              <input type="date" value={newDueDate} onChange={e => setNewDueDate(e.target.value)} className="deci-input" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, paddingBottom: 4 }}>
              <input type="checkbox" checked={newCrossFunctional} onChange={e => setNewCrossFunctional(e.target.checked)} id="cf-check" />
              <label htmlFor="cf-check" style={{ fontSize: 11, color: 'var(--muted)' }}>Cross-functional</label>
            </div>
            <div style={{ flex: '1 1 220px' }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Also create in ClickUp (optional)</label>
              <select value={newClickupListId} onChange={e => setNewClickupListId(e.target.value)} className="deci-input" style={{ width: '100%' }}>
                <option value="">— Do not mirror —</option>
                {clickupLists.map(l => (
                  <option key={l.list_id} value={l.list_id}>
                    {l.space_name ? `${l.space_name} · ` : ''}{l.list_name || l.list_id}
                  </option>
                ))}
              </select>
            </div>
            <button className="range-button active" onClick={handleCreate} disabled={creating || !newTitle.trim()}>
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        ) : null}
        {showCreate && selectedDomain ? (
          <div style={{ fontSize: 12, color: 'var(--blue)', padding: '4px 0', borderTop: '1px solid rgba(255,255,255,0.06)', marginTop: 6 }}>
            Domain auto-fill: Driver → {selectedDomain.default_driver_name || 'none'} | Escalation → {selectedDomain.escalation_owner_name || 'none'} ({selectedDomain.escalation_threshold_days}d threshold)
          </div>
        ) : null}
      </section>

      {/* Escalation Warnings */}
      {escalationWarnings.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Escalation Alerts</strong>
            <span className="badge badge-bad">{escalationWarnings.length} decisions overdue</span>
          </div>
          <div className="stack-list compact">
            {escalationWarnings.map(w => (
              <div key={w.id} className="list-item status-bad" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(w.id)}>
                <div className="item-head">
                  <strong>{w.title}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-bad">{w.days_stale}d stale (threshold: {w.threshold_days}d)</span>
                    <span className="badge badge-muted">{w.domain}</span>
                  </div>
                </div>
                {w.escalation_owner ? (
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Escalation owner: <strong style={{ color: 'var(--orange)' }}>{w.escalation_owner}</strong></div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Decision Bottleneck Panel */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Decision Bottlenecks</strong>
          <span className="venom-panel-hint">{bottlenecks.length} issues found</span>
        </div>
        {bottlenecks.length > 0 ? (
          <div className="stack-list compact">
            {bottlenecks.map((b, i) => (
              <div key={`${b.id}-${i}`} className="list-item status-bad" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(b.id)}>
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
                      {d.cross_functional ? <span className="badge badge-warn">Cross-func</span> : null}
                    </div>
                  </div>
                  <div className="venom-mention-meta">
                    <span className="badge badge-neutral">D: {d.driver_name || 'NONE'}</span>
                    <span className="badge badge-muted">{formatTimeAgo(d.updated_at)}</span>
                    {d.department ? <span className="badge badge-muted">{d.department}</span> : null}
                    {d.due_date ? <span className="badge badge-muted">Due: {formatDate(d.due_date)}</span> : null}
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
              <span className="mini-stat-label">Avg Creation → Decision</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{overview.velocity.avg_decision_to_complete_hours != null ? `${Math.round(overview.velocity.avg_decision_to_complete_hours)}h` : '—'}</span>
              <span className="mini-stat-label">Avg Decision → Complete</span>
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
            <div className="mini-stat">
              <span className="mini-stat-value" style={{ color: escalated > 0 ? 'var(--red)' : undefined }}>{fmtInt(escalated)}</span>
              <span className="mini-stat-label">Escalations</span>
            </div>
            <div className="mini-stat">
              <span className="mini-stat-value">{fmtInt(crossFunctional)}</span>
              <span className="mini-stat-label">Cross-Functional</span>
            </div>
          </div>
        </section>
      ) : null}
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 2: Company Decision Map
// ═══════════════════════════════════════════════════════
function DecisionMapView({ decisions, team, domains, onOpenDetail, onReload }: {
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  domains: DeciDomain[]
  onOpenDetail: (id: string) => void
  onReload: () => void
}) {
  const [seeding, setSeeding] = useState(false)

  // Group domains by category
  const domainsByCategory = useMemo(() => {
    const map: Record<string, DeciDomain[]> = {}
    for (const d of domains.filter(d => d.active)) {
      const cat = d.category || 'operations'
      if (!map[cat]) map[cat] = []
      map[cat].push(d)
    }
    return map
  }, [domains])

  // Category labels
  const CATEGORY_LABELS: Record<string, string> = {
    product: 'Product & Innovation',
    manufacturing: 'Manufacturing & Quality',
    commercial: 'Commercial & Revenue',
    cx: 'Customer Experience',
    engineering: 'Technology & Engineering',
    operations: 'Operations & Org',
  }

  // Decisions by domain
  const decisionsByDomain = useMemo(() => {
    const map: Record<number, DeciDecision[]> = {}
    for (const d of decisions) {
      if (d.domain_id) {
        if (!map[d.domain_id]) map[d.domain_id] = []
        map[d.domain_id].push(d)
      }
    }
    return map
  }, [decisions])

  // Unassigned decisions (no domain)
  const unassigned = useMemo(() => decisions.filter(d => !d.domain_id), [decisions])

  // Cross-functional hot zones
  const crossFunctionalDecisions = useMemo(() =>
    decisions.filter(d => d.cross_functional && d.status !== 'complete')
      .sort((a, b) => {
        const pOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
        return (pOrder[a.priority] ?? 9) - (pOrder[b.priority] ?? 9)
      })
  , [decisions])

  // Leadership cards
  const leadershipCards = useMemo(() => {
    const leaders: { member: DeciTeamMember; domainCount: number; activeDecisions: number; blockedDecisions: number }[] = []
    for (const m of team.filter(t => t.active)) {
      const driverDomains = domains.filter(d => d.default_driver_id === m.id).length
      const escalationDomains = domains.filter(d => d.escalation_owner_id === m.id).length
      if (driverDomains > 0 || escalationDomains > 0) {
        const active = decisions.filter(d => d.driver_id === m.id && d.status !== 'complete').length
        const blocked = decisions.filter(d => d.driver_id === m.id && d.status === 'blocked').length
        leaders.push({ member: m, domainCount: driverDomains + escalationDomains, activeDecisions: active, blockedDecisions: blocked })
      }
    }
    return leaders.sort((a, b) => b.domainCount - a.domainCount)
  }, [team, domains, decisions])

  async function handleSeedDomains() {
    setSeeding(true)
    try {
      await api.deciSeedDomains()
      onReload()
    } finally {
      setSeeding(false)
    }
  }

  if (domains.length === 0) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Decision Map</strong></div>
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '8px 0 16px' }}>
          No decision domains configured. Seed the default 12 governance domains to build your company decision map.
        </p>
        <button className="range-button active" onClick={handleSeedDomains} disabled={seeding}>
          {seeding ? 'Seeding...' : 'Seed Default Domains'}
        </button>
      </section>
    )
  }

  return (
    <>
      {/* Leadership Cards */}
      {leadershipCards.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Leadership Accountability</strong>
            <span className="venom-panel-hint">{leadershipCards.length} domain owners</span>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {leadershipCards.map(l => (
              <div key={l.member.id} style={{
                padding: '12px 16px', background: 'rgba(255,255,255,0.04)', borderRadius: 8, minWidth: 160,
                borderLeft: l.blockedDecisions > 0 ? '3px solid var(--red)' : '3px solid var(--green)',
              }}>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{l.member.name}</div>
                {l.member.role ? <div style={{ fontSize: 11, color: 'var(--muted)' }}>{l.member.role}</div> : null}
                {l.member.department ? <div style={{ fontSize: 11, color: 'var(--muted)' }}>{l.member.department}</div> : null}
                <div style={{ fontSize: 12, marginTop: 8, display: 'flex', gap: 12 }}>
                  <span>{l.domainCount} domain{l.domainCount !== 1 ? 's' : ''}</span>
                  <span style={{ color: 'var(--green)' }}>{l.activeDecisions} active</span>
                  {l.blockedDecisions > 0 ? <span style={{ color: 'var(--red)', fontWeight: 700 }}>{l.blockedDecisions} blocked</span> : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Domain Table by Category */}
      {Object.entries(domainsByCategory).map(([category, categoryDomains]) => (
        <section key={category} className="card">
          <div className="venom-panel-head">
            <strong style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: DOMAIN_CATEGORY_COLORS[category] || '#6b7280', display: 'inline-block' }} />
              {CATEGORY_LABELS[category] || category}
            </strong>
            <span className="venom-panel-hint">{categoryDomains.length} domains</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Domain</th>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Default Driver</th>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Escalation Owner</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Threshold</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Active</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Total</th>
                </tr>
              </thead>
              <tbody>
                {categoryDomains.map(dom => {
                  const domDecisions = decisionsByDomain[dom.id] || []
                  const activeCount = domDecisions.filter(d => d.status !== 'complete').length
                  return (
                    <tr key={dom.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px' }}>
                        <div style={{ fontWeight: 500 }}>{dom.name}</div>
                        {dom.description ? <div style={{ fontSize: 11, color: 'var(--muted)', maxWidth: 400 }}>{dom.description}</div> : null}
                      </td>
                      <td style={{ padding: '6px 8px', color: dom.default_driver_name ? undefined : 'var(--red)' }}>
                        {dom.default_driver_name || 'Not configured in matrix'}
                      </td>
                      <td style={{ padding: '6px 8px', color: dom.escalation_owner_name ? undefined : 'var(--muted)' }}>
                        {dom.escalation_owner_name || '—'}
                      </td>
                      <td style={{ textAlign: 'center', padding: '6px 8px' }}>{dom.escalation_threshold_days}d</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px', color: activeCount > 0 ? 'var(--green)' : 'var(--muted)' }}>{activeCount}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px' }}>{domDecisions.length}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      {/* Cross-Functional Hot Zones */}
      {crossFunctionalDecisions.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Cross-Functional Hot Zones</strong>
            <span className="badge badge-warn">{crossFunctionalDecisions.length} active</span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 10px' }}>
            Decisions that span multiple departments or domains — high coordination risk.
          </p>
          <div className="stack-list compact">
            {crossFunctionalDecisions.map(d => (
              <div key={d.id} className={`list-item status-${statusColor(d.status)}`} style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <div className="inline-badges">
                    <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                    <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus]}</span>
                    <span className="badge badge-warn">Cross-functional</span>
                  </div>
                </div>
                <div className="venom-mention-meta">
                  <span className="badge badge-neutral">D: {d.driver_name || 'NONE'}</span>
                  {d.department ? <span className="badge badge-muted">{d.department}</span> : null}
                  {d.due_date ? <span className="badge badge-muted">Due: {formatDate(d.due_date)}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Unassigned Decisions */}
      {unassigned.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Decisions Without Domain</strong>
            <span className="badge badge-warn">{unassigned.length} unassigned</span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 10px' }}>
            These decisions haven't been assigned to a governance domain. Assign them to enable escalation rules and ownership tracking.
          </p>
          <div className="stack-list compact">
            {unassigned.slice(0, 10).map(d => (
              <div key={d.id} className={`list-item status-${statusColor(d.status)}`} style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(d.id)}>
                <div className="item-head">
                  <strong>{d.title}</strong>
                  <div className="inline-badges">
                    <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                    <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus]}</span>
                  </div>
                </div>
              </div>
            ))}
            {unassigned.length > 10 ? <div className="state-message">...and {unassigned.length - 10} more</div> : null}
          </div>
        </section>
      ) : null}
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 3: Active Decisions
// ═══════════════════════════════════════════════════════
function ActiveDecisionsView({ decisions, team, domains, onOpenDetail, onReload, filterStatus, setFilterStatus, filterDept, setFilterDept, filterPriority, setFilterPriority, filterDomain, setFilterDomain }: {
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  domains: DeciDomain[]
  onOpenDetail: (id: string) => void
  onReload: () => void
  filterStatus: string; setFilterStatus: (s: string) => void
  filterDept: string; setFilterDept: (s: string) => void
  filterPriority: string; setFilterPriority: (s: string) => void
  filterDomain: string; setFilterDomain: (s: string) => void
}) {
  const domainMap = useMemo(() => {
    const map: Record<number, string> = {}
    for (const d of domains) map[d.id] = d.name
    return map
  }, [domains])

  const filtered = useMemo(() => {
    let result = [...decisions]
    if (filterStatus) result = result.filter(d => d.status === filterStatus)
    if (filterDept) result = result.filter(d => d.department === filterDept)
    if (filterPriority) result = result.filter(d => d.priority === filterPriority)
    if (filterDomain) result = result.filter(d => d.domain_id?.toString() === filterDomain)
    return result.sort((a, b) => {
      const pOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      const sOrder: Record<string, number> = { blocked: 0, in_progress: 1, not_started: 2, complete: 3 }
      const pDiff = (pOrder[a.priority] ?? 9) - (pOrder[b.priority] ?? 9)
      if (pDiff !== 0) return pDiff
      return (sOrder[a.status] ?? 9) - (sOrder[b.status] ?? 9)
    })
  }, [decisions, filterStatus, filterDept, filterPriority, filterDomain])

  const { user } = useAuth()
  const canDelete = user?.email === 'joseph@spidergrills.com'

  // Inline status update
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  async function handleQuickStatusUpdate(id: string, newStatus: DeciStatus) {
    setUpdatingId(id)
    try {
      await api.deciUpdateDecision(id, { status: newStatus })
      onReload()
    } finally {
      setUpdatingId(null)
    }
  }

  async function handleDelete(id: string, title: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return
    setDeletingId(id)
    try {
      await api.deciDeleteDecision(id)
      onReload()
    } finally {
      setDeletingId(null)
    }
  }

  async function handleInlineRoleAdd(d: DeciDecision, role: 'executors' | 'contributors' | 'informed', memberId: number) {
    const existing = (d[role] as Array<{ member_id: number }> || []).map(a => a.member_id)
    if (existing.includes(memberId)) return
    try {
      await api.deciUpdateDecision(d.id, { [role]: [...existing, memberId] })
      onReload()
    } catch { /* ignore */ }
  }

  async function handleInlineRoleRemove(d: DeciDecision, role: 'executors' | 'contributors' | 'informed', memberId: number) {
    const existing = (d[role] as Array<{ member_id: number }> || []).map(a => a.member_id)
    try {
      await api.deciUpdateDecision(d.id, { [role]: existing.filter(id => id !== memberId) })
      onReload()
    } catch { /* ignore */ }
  }

  return (
    <>
      <section className="card">
        <div className="venom-panel-head">
          <strong>Active Decisions</strong>
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
          {domains.length > 0 ? (
            <select value={filterDomain} onChange={e => setFilterDomain(e.target.value)} className="deci-input">
              <option value="">All domains</option>
              {domains.filter(d => d.active).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          ) : null}
        </div>

        {filtered.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 1100 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Decision</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>Domain</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>D</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>E — Executors</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>C — Contributors</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>I — Informed</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Status</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Priority</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Due</th>
                  <th style={{ textAlign: 'right', padding: '8px' }}>Updated</th>
                  <th style={{ textAlign: 'center', padding: '8px', width: 100 }}>Quick</th>
                  {canDelete && <th style={{ textAlign: 'center', padding: '8px', width: 40 }}></th>}
                </tr>
              </thead>
              <tbody>
                {filtered.map(d => {
                  const isStale = d.status !== 'complete' && daysSince(d.updated_at) > 7
                  const noDriver = !d.driver_id
                  const noExecutor = (d.executors?.length ?? 0) === 0 && d.status === 'in_progress'
                  const isOverdue = d.due_date && new Date(d.due_date) < new Date() && d.status !== 'complete'
                  const rowStyle: React.CSSProperties = {
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    cursor: 'pointer',
                    background: noDriver ? 'rgba(255,80,80,0.08)' : noExecutor ? 'rgba(255,160,80,0.08)' : isStale ? 'rgba(255,200,80,0.06)' : undefined,
                  }
                  return (
                    <tr key={d.id} style={rowStyle} onClick={() => onOpenDetail(d.id)}>
                      <td style={{ padding: '8px', fontWeight: 500 }}>
                        <div>{d.title}</div>
                        <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
                          {d.department ? <span style={{ fontSize: 10, color: 'var(--muted)' }}>{d.department}</span> : null}
                          {d.cross_functional ? <span className="badge badge-warn" style={{ fontSize: 9, padding: '0 4px' }}>CF</span> : null}
                          {d.escalation_status && d.escalation_status !== 'none' ? <span className={`badge ${escalationBadge(d.escalation_status)}`} style={{ fontSize: 9, padding: '0 4px' }}>{d.escalation_status}</span> : null}
                        </div>
                      </td>
                      <td style={{ padding: '8px', fontSize: 11, color: 'var(--muted)' }}>
                        {d.domain_id ? (domainMap[d.domain_id] || `Domain #${d.domain_id}`) : '—'}
                      </td>
                      <td style={{ padding: '8px', color: noDriver ? 'var(--red)' : undefined, fontWeight: noDriver ? 700 : 400 }}>
                        {d.driver_name || (noDriver ? 'MISSING' : '—')}
                      </td>
                      {/* E — Executors */}
                      <td style={{ padding: '6px 8px', verticalAlign: 'top' }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'center' }}>
                          {(d.executors?.length ?? 0) > 0 ? d.executors.map(a => (
                            <span key={a.id} style={{ fontSize: 11, background: 'rgba(57,208,143,0.15)', border: '1px solid rgba(57,208,143,0.3)', borderRadius: 4, padding: '1px 5px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                              {a.member_name}
                              <span style={{ cursor: 'pointer', opacity: 0.6, fontSize: 10 }} onClick={() => handleInlineRoleRemove(d, 'executors', a.member_id)} title="Remove">&times;</span>
                            </span>
                          )) : <span style={{ color: noExecutor ? 'var(--orange)' : 'var(--muted)', fontSize: 11 }}>{noExecutor ? 'MISSING' : '—'}</span>}
                          <select
                            value=""
                            onChange={e => { if (e.target.value) handleInlineRoleAdd(d, 'executors', Number(e.target.value)) }}
                            className="deci-input"
                            style={{ fontSize: 10, padding: '1px 2px', width: 28, opacity: 0.5, cursor: 'pointer' }}
                            title="Add executor"
                          >
                            <option value="">+</option>
                            {team.filter(m => m.active && !d.executors?.some(a => a.member_id === m.id)).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                          </select>
                        </div>
                      </td>
                      {/* C — Contributors */}
                      <td style={{ padding: '6px 8px', verticalAlign: 'top' }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'center' }}>
                          {(d.contributors?.length ?? 0) > 0 ? d.contributors.map(a => (
                            <span key={a.id} style={{ fontSize: 11, background: 'rgba(159,176,212,0.12)', border: '1px solid rgba(159,176,212,0.25)', borderRadius: 4, padding: '1px 5px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                              {a.member_name}
                              <span style={{ cursor: 'pointer', opacity: 0.6, fontSize: 10 }} onClick={() => handleInlineRoleRemove(d, 'contributors', a.member_id)} title="Remove">&times;</span>
                            </span>
                          )) : <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>}
                          <select
                            value=""
                            onChange={e => { if (e.target.value) handleInlineRoleAdd(d, 'contributors', Number(e.target.value)) }}
                            className="deci-input"
                            style={{ fontSize: 10, padding: '1px 2px', width: 28, opacity: 0.5, cursor: 'pointer' }}
                            title="Add contributor"
                          >
                            <option value="">+</option>
                            {team.filter(m => m.active && !d.contributors?.some(a => a.member_id === m.id)).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                          </select>
                        </div>
                      </td>
                      {/* I — Informed */}
                      <td style={{ padding: '6px 8px', verticalAlign: 'top' }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'center' }}>
                          {(d.informed?.length ?? 0) > 0 ? d.informed.map(a => (
                            <span key={a.id} style={{ fontSize: 11, background: 'rgba(159,176,212,0.08)', border: '1px solid rgba(159,176,212,0.15)', borderRadius: 4, padding: '1px 5px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                              {a.member_name}
                              <span style={{ cursor: 'pointer', opacity: 0.6, fontSize: 10 }} onClick={() => handleInlineRoleRemove(d, 'informed', a.member_id)} title="Remove">&times;</span>
                            </span>
                          )) : <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>}
                          <select
                            value=""
                            onChange={e => { if (e.target.value) handleInlineRoleAdd(d, 'informed', Number(e.target.value)) }}
                            className="deci-input"
                            style={{ fontSize: 10, padding: '1px 2px', width: 28, opacity: 0.5, cursor: 'pointer' }}
                            title="Add informed"
                          >
                            <option value="">+</option>
                            {team.filter(m => m.active && !d.informed?.some(a => a.member_id === m.id)).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                          </select>
                        </div>
                      </td>
                      <td style={{ textAlign: 'center', padding: '8px' }}>
                        <span className={`badge badge-${statusColor(d.status)}`}>{STATUS_LABELS[d.status as DeciStatus] || d.status}</span>
                      </td>
                      <td style={{ textAlign: 'center', padding: '8px' }}>
                        <span className={`badge ${priorityBadge(d.priority)}`}>{d.priority}</span>
                      </td>
                      <td style={{ textAlign: 'center', padding: '8px', color: isOverdue ? 'var(--red)' : 'var(--muted)', fontWeight: isOverdue ? 700 : 400, fontSize: 11 }}>
                        {d.due_date ? formatDate(d.due_date) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px', color: isStale ? 'var(--orange)' : 'var(--muted)' }}>
                        {formatTimeAgo(d.updated_at)}
                      </td>
                      <td style={{ textAlign: 'center', padding: '4px' }} onClick={e => e.stopPropagation()}>
                        {d.status !== 'complete' ? (
                          <select
                            value={d.status}
                            onChange={e => handleQuickStatusUpdate(d.id, e.target.value as DeciStatus)}
                            disabled={updatingId === d.id}
                            className="deci-input"
                            style={{ fontSize: 10, padding: '2px 4px', width: 90 }}
                          >
                            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        ) : <span className="badge badge-good" style={{ fontSize: 10 }}>Done</span>}
                      </td>
                      {canDelete && (
                        <td style={{ textAlign: 'center', padding: '4px' }} onClick={e => e.stopPropagation()}>
                          <button
                            onClick={() => handleDelete(d.id, d.title)}
                            disabled={deletingId === d.id}
                            title="Delete decision"
                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--red)', fontSize: 14, opacity: deletingId === d.id ? 0.4 : 0.6, padding: '2px 6px' }}
                            onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                            onMouseLeave={e => (e.currentTarget.style.opacity = '0.6')}
                          >
                            {deletingId === d.id ? '…' : '✕'}
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : <div className="state-message">No decisions match these filters. Create a new decision from the Executive Overview.</div>}
      </section>

      {/* Status Summary Bar */}
      {decisions.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Status Distribution</strong>
          </div>
          <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden', marginTop: 4 }}>
            {(['not_started', 'in_progress', 'blocked', 'complete'] as DeciStatus[]).map(s => {
              const count = decisions.filter(d => d.status === s).length
              const pct = decisions.length > 0 ? (count / decisions.length) * 100 : 0
              if (pct === 0) return null
              const colors: Record<string, string> = { not_started: '#6b7280', in_progress: '#f59e0b', blocked: '#ef4444', complete: '#10b981' }
              return (
                <div key={s} style={{ width: `${pct}%`, background: colors[s], display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', fontWeight: 600, minWidth: pct > 5 ? 40 : 0 }}
                  title={`${STATUS_LABELS[s]}: ${count} (${Math.round(pct)}%)`}>
                  {pct > 10 ? `${STATUS_LABELS[s]} ${count}` : pct > 5 ? `${count}` : ''}
                </div>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: 16, marginTop: 8, flexWrap: 'wrap' }}>
            {(['not_started', 'in_progress', 'blocked', 'complete'] as DeciStatus[]).map(s => {
              const count = decisions.filter(d => d.status === s).length
              const colors: Record<string, string> = { not_started: '#6b7280', in_progress: '#f59e0b', blocked: '#ef4444', complete: '#10b981' }
              return (
                <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: colors[s] }} />
                  <span style={{ color: 'var(--muted)' }}>{STATUS_LABELS[s]}:</span>
                  <strong>{count}</strong>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 4: Decision Detail
// ═══════════════════════════════════════════════════════
function DetailView({ decisionId, team, domains, onBack, onReload }: {
  decisionId: string
  team: DeciTeamMember[]
  domains: DeciDomain[]
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
  const [editDomainId, setEditDomainId] = useState<number | ''>('')
  const [editCrossFunctional, setEditCrossFunctional] = useState(false)
  const [editDescription, setEditDescription] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editEscalation, setEditEscalation] = useState('none')

  // Log entry
  const [logText, setLogText] = useState('')
  const [logBy, setLogBy] = useState('')
  const [logNotes, setLogNotes] = useState('')
  const [addingLog, setAddingLog] = useState(false)

  // KPI link
  const [kpiName, setKpiName] = useState('')
  const [addingKpi, setAddingKpi] = useState(false)

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
      setEditDomainId(d.domain_id || '')
      setEditDescription(d.description || '')
      setEditCrossFunctional(d.cross_functional ?? false)
      setEditDueDate(d.due_date || '')
      setEditEscalation(d.escalation_status || 'none')
    } finally {
      setLoading(false)
    }
  }, [decisionId])

  /** Silent re-fetch — updates state without showing loading spinner or resetting scroll */
  const silentLoadDecision = useCallback(async () => {
    try {
      const d = await api.deciDecision(decisionId)
      setDecision(d)
      setEditStatus(d.status)
      setEditPriority(d.priority)
      setEditDriverId(d.driver_id || '')
      setEditDept(d.department || '')
      setEditDomainId(d.domain_id || '')
      setEditDescription(d.description || '')
      setEditCrossFunctional(d.cross_functional ?? false)
      setEditDueDate(d.due_date || '')
      setEditEscalation(d.escalation_status || 'none')
    } catch { /* silent */ }
  }, [decisionId])

  useEffect(() => { void loadDecision() }, [loadDecision])

  const domainName = useMemo(() => {
    if (!decision?.domain_id) return null
    return domains.find(d => d.id === decision.domain_id)?.name ?? null
  }, [decision, domains])

  async function handleSave() {
    if (!decision) return
    setSaving(true)
    try {
      if (editStatus === 'in_progress' && !editDriverId) {
        alert('Cannot set status to In Progress without a Driver assigned.')
        setSaving(false)
        return
      }
      await api.deciUpdateDecision(decision.id, {
        status: editStatus,
        priority: editPriority,
        description: editDescription || null,
        driver_id: editDriverId || null,
        department: editDept || null,
        domain_id: editDomainId || null,
        cross_functional: editCrossFunctional,
        due_date: editDueDate || null,
        escalation_status: editEscalation,
      })
      await silentLoadDecision()
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
      await silentLoadDecision()
    } finally {
      setAddingLog(false)
    }
  }

  async function handleAddKpiLink() {
    if (!decision || !kpiName.trim()) return
    setAddingKpi(true)
    try {
      await api.deciAddKpiLink(decision.id, { kpi_name: kpiName.trim() })
      setKpiName('')
      await silentLoadDecision()
    } finally {
      setAddingKpi(false)
    }
  }

  async function handleRemoveKpiLink(linkId: number) {
    if (!decision) return
    try {
      await api.deciDeleteKpiLink(decision.id, linkId)
      await silentLoadDecision()
    } catch { /* ignore */ }
  }

  async function handleAddAssignment() {
    if (!decision || !addMemberId) return
    try {
      const body: Record<string, unknown> = {
        status: decision.status,
        priority: decision.priority,
        driver_id: decision.driver_id,
        department: decision.department,
        [`${addRole}s`]: [...(decision[`${addRole}s` as keyof DeciDecision] as Array<{member_id: number}> || []).map(a => a.member_id), Number(addMemberId)],
      }
      await api.deciUpdateDecision(decision.id, body)
      setAddMemberId('')
      await silentLoadDecision()
      onReload()
    } catch { /* ignore */ }
  }

  if (loading) return <Card title="Loading"><div className="state-message">Loading decision...</div></Card>
  if (!decision) return <Card title="Not Found"><div className="state-message">Decision not found.</div></Card>

  const isOverdue = decision.due_date && new Date(decision.due_date) < new Date() && decision.status !== 'complete'
  const isStale = decision.status !== 'complete' && daysSince(decision.updated_at) > 7

  return (
    <>
      {/* Back button */}
      <div style={{ marginBottom: 8 }}>
        <button className="range-button" onClick={onBack}>&larr; Back to Active Decisions</button>
      </div>

      {/* Header */}
      <section className="card">
        <div className="venom-panel-head">
          <strong style={{ fontSize: 16 }}>{decision.title}</strong>
          <div className="inline-badges">
            <span className={`badge badge-${statusColor(decision.status)}`}>{STATUS_LABELS[decision.status] || decision.status}</span>
            <span className={`badge ${priorityBadge(decision.priority)}`}>{decision.priority}</span>
            <span className="badge badge-muted">{TYPE_LABELS[decision.type] || decision.type}</span>
            {decision.cross_functional ? <span className="badge badge-warn">Cross-functional</span> : null}
            {decision.escalation_status && decision.escalation_status !== 'none' ? <span className={`badge ${escalationBadge(decision.escalation_status)}`}>{decision.escalation_status}</span> : null}
          </div>
        </div>
        {decision.description ? <p style={{ color: 'var(--muted)', fontSize: 13, margin: '8px 0 0' }}>{decision.description}</p> : null}
        <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 12, color: 'var(--muted)', flexWrap: 'wrap' }}>
          {domainName ? <span>Domain: <strong>{domainName}</strong></span> : null}
          {decision.department ? <span>Dept: <strong>{decision.department}</strong></span> : null}
          {decision.due_date ? <span style={{ color: isOverdue ? 'var(--red)' : undefined }}>Due: <strong>{formatDate(decision.due_date)}</strong>{isOverdue ? ' (OVERDUE)' : ''}</span> : null}
          <span>Created: {formatDate(decision.created_at)}</span>
          <span style={{ color: isStale ? 'var(--orange)' : undefined }}>Updated: {formatTimeAgo(decision.updated_at)}{isStale ? ' (STALE)' : ''}</span>
          {decision.resolved_at ? <span style={{ color: 'var(--green)' }}>Resolved: {formatDate(decision.resolved_at)}</span> : null}
        </div>
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
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>E — EXECUTORS ({decision.executors?.length ?? 0})</div>
            {decision.executors?.map(e => (
              <span key={e.id} className="badge badge-good" style={{ marginRight: 4, marginBottom: 4 }}>{e.member_name}</span>
            ))}
            {(decision.executors?.length ?? 0) === 0 ? <span style={{ fontSize: 12, color: 'var(--orange)' }}>None assigned</span> : null}
          </div>
          {/* Contributors */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>C — CONTRIBUTORS ({decision.contributors?.length ?? 0})</div>
            {decision.contributors?.map(c => (
              <span key={c.id} className="badge badge-neutral" style={{ marginRight: 4, marginBottom: 4 }}>{c.member_name}</span>
            ))}
            {(decision.contributors?.length ?? 0) === 0 ? <span style={{ fontSize: 12, color: 'var(--muted)' }}>None</span> : null}
            {(decision.contributors?.length ?? 0) > 5 ? <span className="badge badge-warn" style={{ marginLeft: 4 }}>Too many contributors — governance risk!</span> : null}
          </div>
          {/* Informed */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 4 }}>I — INFORMED ({decision.informed?.length ?? 0})</div>
            {decision.informed?.map(inf => (
              <span key={inf.id} className="badge badge-muted" style={{ marginRight: 4, marginBottom: 4 }}>{inf.member_name}</span>
            ))}
            {(decision.informed?.length ?? 0) === 0 ? <span style={{ fontSize: 12, color: 'var(--muted)' }}>None</span> : null}
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
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Description</label>
              <textarea value={editDescription} onChange={e => setEditDescription(e.target.value)} placeholder="What is this decision about? Context, goals, constraints..." rows={3} style={{ width: '100%', resize: 'vertical' }} className="deci-input" />
            </div>
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
            {domains.length > 0 ? (
              <div>
                <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Domain</label>
                <select value={editDomainId} onChange={e => setEditDomainId(e.target.value ? Number(e.target.value) : '')} className="deci-input" style={{ width: '100%' }}>
                  <option value="">— None —</option>
                  {domains.filter(d => d.active).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
            ) : null}
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Due Date</label>
              <input type="date" value={editDueDate} onChange={e => setEditDueDate(e.target.value)} className="deci-input" style={{ width: '100%' }} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Escalation Status</label>
              <select value={editEscalation} onChange={e => setEditEscalation(e.target.value)} className="deci-input" style={{ width: '100%' }}>
                <option value="none">None</option>
                <option value="warning">Warning</option>
                <option value="escalated">Escalated</option>
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={editCrossFunctional} onChange={e => setEditCrossFunctional(e.target.checked)} id="cf-detail" />
              <label htmlFor="cf-detail" style={{ fontSize: 12, color: 'var(--muted)' }}>Cross-functional decision</label>
            </div>
            <button className="range-button active" onClick={handleSave} disabled={saving} style={{ width: '100%', marginTop: 8 }}>
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {/* KPI Links */}
          <div style={{ marginTop: 16, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 6 }}>Linked KPIs</div>
            {decision.kpi_links?.map(link => (
              <span key={link.id} className="badge badge-good" style={{ marginRight: 4, marginBottom: 4, cursor: 'pointer' }} onClick={() => handleRemoveKpiLink(link.id)} title="Click to remove">
                {link.kpi_name} &times;
              </span>
            ))}
            {(decision.kpi_links?.length ?? 0) === 0 ? <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>No KPIs linked</div> : null}
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <select value={kpiName} onChange={e => setKpiName(e.target.value)} className="deci-input">
                <option value="">Select KPI...</option>
                <optgroup label="Financial / Revenue">
                  <option value="Revenue">Revenue</option>
                  <option value="Gross Profit">Gross Profit</option>
                  <option value="Refunds">Refunds</option>
                  <option value="Discounts">Discounts</option>
                  <option value="Discount Rate">Discount Rate</option>
                  <option value="Ad Spend">Ad Spend</option>
                  <option value="Orders">Orders</option>
                  <option value="AOV">AOV (Avg Order Value)</option>
                  <option value="Revenue Per Session">Revenue Per Session</option>
                  <option value="MER">MER (Marketing Efficiency)</option>
                  <option value="Cost Per Purchase">Cost Per Purchase</option>
                </optgroup>
                <optgroup label="Conversion / Funnel">
                  <option value="Sessions">Sessions</option>
                  <option value="Conversion Rate">Conversion Rate</option>
                  <option value="Bounce Rate">Bounce Rate</option>
                  <option value="Add to Cart Rate">Add to Cart Rate</option>
                  <option value="Cart Abandonment Rate">Cart Abandonment Rate</option>
                  <option value="Checkout Completion Rate">Checkout Completion Rate</option>
                </optgroup>
                <optgroup label="Customer Experience">
                  <option value="CSAT">CSAT</option>
                  <option value="First Response Time">First Response Time</option>
                  <option value="Resolution Time">Resolution Time</option>
                  <option value="Ticket Volume">Ticket Volume</option>
                  <option value="SLA Breach Rate">SLA Breach Rate</option>
                  <option value="Reopen Rate">Reopen Rate</option>
                  <option value="Open Backlog">Open Backlog</option>
                  <option value="Tickets per 100 Orders">Tickets per 100 Orders</option>
                  <option value="First Contact Resolution">First Contact Resolution</option>
                </optgroup>
                <optgroup label="Product / Telemetry">
                  <option value="Cook Success Rate">Cook Success Rate</option>
                  <option value="Disconnect Rate">Disconnect Rate</option>
                  <option value="Temperature Stability">Temperature Stability</option>
                  <option value="Active Devices">Active Devices</option>
                  <option value="Error Rate">Error Rate</option>
                  <option value="Overshoot Rate">Overshoot Rate</option>
                  <option value="Time to Stabilize">Time to Stabilize</option>
                  <option value="RSSI Signal Strength">RSSI Signal Strength</option>
                  <option value="Probe Error Rate">Probe Error Rate</option>
                  <option value="Fleet Reliability">Fleet Reliability</option>
                </optgroup>
                <optgroup label="Social / Brand">
                  <option value="Brand Mentions">Brand Mentions</option>
                  <option value="Sentiment Score">Sentiment Score</option>
                  <option value="Share of Voice">Share of Voice</option>
                  <option value="Competitor Mentions">Competitor Mentions</option>
                  <option value="YouTube Engagement">YouTube Engagement</option>
                </optgroup>
                <optgroup label="Operational">
                  <option value="Issue Resolution Rate">Issue Resolution Rate</option>
                  <option value="Escalation Count">Escalation Count</option>
                  <option value="Decision Velocity">Decision Velocity</option>
                  <option value="Source Health Coverage">Source Health Coverage</option>
                  <option value="Amazon BSR">Amazon BSR</option>
                </optgroup>
              </select>
              <button className="range-button active" onClick={handleAddKpiLink} disabled={addingKpi || !kpiName}>Link</button>
            </div>
          </div>
        </section>
      </div>

      {/* Decision Timeline */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Decision Timeline</strong>
          <span className="venom-panel-hint">{decision.logs?.length ?? 0} entries</span>
        </div>
        {(decision.logs?.length ?? 0) > 0 ? (
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

      {/* Action Panel */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Automation Flags</strong>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {!decision.driver_id ? (
            <div style={{ padding: '8px 12px', background: 'rgba(239,68,68,0.1)', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>
              <strong style={{ color: 'var(--red)' }}>Missing Driver</strong>
              <div style={{ color: 'var(--muted)', marginTop: 2 }}>This decision has no owner. Assign a Driver before moving to In Progress.</div>
            </div>
          ) : null}
          {isStale ? (
            <div style={{ padding: '8px 12px', background: 'rgba(245,158,11,0.1)', borderRadius: 8, border: '1px solid rgba(245,158,11,0.3)', fontSize: 12 }}>
              <strong style={{ color: 'var(--orange)' }}>Stale Decision</strong>
              <div style={{ color: 'var(--muted)', marginTop: 2 }}>No updates in {daysSince(decision.updated_at)} days. Add a log entry or update the status.</div>
            </div>
          ) : null}
          {isOverdue ? (
            <div style={{ padding: '8px 12px', background: 'rgba(239,68,68,0.1)', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>
              <strong style={{ color: 'var(--red)' }}>Overdue</strong>
              <div style={{ color: 'var(--muted)', marginTop: 2 }}>Due date was {formatDate(decision.due_date)}. Update the deadline or complete the decision.</div>
            </div>
          ) : null}
          {(decision.contributors?.length ?? 0) > 5 ? (
            <div style={{ padding: '8px 12px', background: 'rgba(245,158,11,0.1)', borderRadius: 8, border: '1px solid rgba(245,158,11,0.3)', fontSize: 12 }}>
              <strong style={{ color: 'var(--orange)' }}>Contributor Bloat</strong>
              <div style={{ color: 'var(--muted)', marginTop: 2 }}>{decision.contributors.length} contributors is too many. Reduce to 5 or fewer to maintain decision clarity.</div>
            </div>
          ) : null}
          {!decision.driver_id && !isStale && !isOverdue && (decision.contributors?.length ?? 0) <= 5 ? (
            <div style={{ color: 'var(--green)', fontSize: 12 }}>No automation flags. This decision is well-managed.</div>
          ) : null}
          {decision.driver_id && !isStale && !isOverdue && (decision.contributors?.length ?? 0) <= 5 ? (
            <div style={{ color: 'var(--green)', fontSize: 12 }}>No automation flags. This decision is well-managed.</div>
          ) : null}
        </div>
      </section>
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 5: Role Load & Accountability
// ═══════════════════════════════════════════════════════
function RoleLoadView({ decisions, team, domains, onOpenDetail }: {
  decisions: DeciDecision[]
  team: DeciTeamMember[]
  domains: DeciDomain[]
  onOpenDetail: (id: string) => void
}) {
  // Build role load data
  const roleLoadData = useMemo(() => {
    return team.filter(m => m.active).map(m => {
      const driving = decisions.filter(d => d.driver_id === m.id)
      const executing = decisions.filter(d => d.executors?.some(e => e.member_id === m.id))
      const contributing = decisions.filter(d => d.contributors?.some(c => c.member_id === m.id))
      const informed = decisions.filter(d => d.informed?.some(inf => inf.member_id === m.id))

      const activeDriving = driving.filter(d => d.status !== 'complete')
      const activeExecuting = executing.filter(d => d.status !== 'complete')
      const blockedDriving = driving.filter(d => d.status === 'blocked')

      const totalLoad = activeDriving.length + activeExecuting.length
      const isOverloaded = activeDriving.length > 5 || totalLoad > 10

      // Domain responsibilities
      const ownedDomains = domains.filter(d => d.default_driver_id === m.id)
      const escalationDomains = domains.filter(d => d.escalation_owner_id === m.id)

      return {
        member: m,
        driving: driving.length,
        activeDriving: activeDriving.length,
        executing: executing.length,
        activeExecuting: activeExecuting.length,
        contributing: contributing.length,
        informed: informed.length,
        blocked: blockedDriving.length,
        totalLoad,
        isOverloaded,
        ownedDomains: ownedDomains.length,
        escalationDomains: escalationDomains.length,
        completionRate: driving.length > 0 ? driving.filter(d => d.status === 'complete').length / driving.length : 0,
      }
    }).sort((a, b) => b.totalLoad - a.totalLoad)
  }, [team, decisions, domains])

  // Max load for bar scaling
  const maxLoad = Math.max(1, ...roleLoadData.map(r => r.totalLoad))

  // Department heatmap
  const deptHeatmap = useMemo(() => {
    const depts = [...new Set(decisions.map(d => d.department).filter(Boolean))] as string[]
    return depts.map(dept => {
      const deptDecisions = decisions.filter(d => d.department === dept)
      const active = deptDecisions.filter(d => d.status !== 'complete').length
      const blocked = deptDecisions.filter(d => d.status === 'blocked').length
      const noDriver = deptDecisions.filter(d => !d.driver_id && d.status !== 'complete').length
      const stale = deptDecisions.filter(d => d.status !== 'complete' && daysSince(d.updated_at) > 7).length
      return { dept, total: deptDecisions.length, active, blocked, noDriver, stale }
    }).sort((a, b) => b.active - a.active)
  }, [decisions])

  // Overload alerts
  const overloaded = roleLoadData.filter(r => r.isOverloaded)

  return (
    <>
      {/* Overload Alerts */}
      {overloaded.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Overload Alerts</strong>
            <span className="badge badge-bad">{overloaded.length} overloaded</span>
          </div>
          <div className="stack-list compact">
            {overloaded.map(r => (
              <div key={r.member.id} className="list-item status-bad">
                <div className="item-head">
                  <strong>{r.member.name}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-bad">{r.totalLoad} active items</span>
                    <span className="badge badge-warn">{r.activeDriving} driving</span>
                    {r.blocked > 0 ? <span className="badge badge-bad">{r.blocked} blocked</span> : null}
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  {r.activeDriving > 5 ? 'Driving too many decisions — redistribute ownership. ' : ''}
                  {r.totalLoad > 10 ? 'Total decision load exceeds recommended threshold of 10.' : ''}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Role Load Table */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Role Load by Person</strong>
          <span className="venom-panel-hint">{roleLoadData.length} team members</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 800 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                <th style={{ textAlign: 'left', padding: '8px' }}>Person</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Driving</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Executing</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Contributing</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Blocked</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Domains</th>
                <th style={{ textAlign: 'center', padding: '8px' }}>Completion</th>
                <th style={{ textAlign: 'left', padding: '8px', width: 200 }}>Load</th>
              </tr>
            </thead>
            <tbody>
              {roleLoadData.map(r => (
                <tr key={r.member.id} style={{
                  borderBottom: '1px solid rgba(255,255,255,0.06)',
                  background: r.isOverloaded ? 'rgba(239,68,68,0.06)' : undefined,
                }}>
                  <td style={{ padding: '8px' }}>
                    <div style={{ fontWeight: 600 }}>{r.member.name}</div>
                    <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                      {[r.member.role, r.member.department].filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  <td style={{ textAlign: 'center', padding: '8px', fontWeight: r.activeDriving > 5 ? 700 : 400, color: r.activeDriving > 5 ? 'var(--red)' : undefined }}>
                    {r.activeDriving}<span style={{ color: 'var(--muted)', fontWeight: 400 }}>/{r.driving}</span>
                  </td>
                  <td style={{ textAlign: 'center', padding: '8px' }}>
                    {r.activeExecuting}<span style={{ color: 'var(--muted)' }}>/{r.executing}</span>
                  </td>
                  <td style={{ textAlign: 'center', padding: '8px', color: 'var(--muted)' }}>{r.contributing}</td>
                  <td style={{ textAlign: 'center', padding: '8px', color: r.blocked > 0 ? 'var(--red)' : 'var(--muted)', fontWeight: r.blocked > 0 ? 700 : 400 }}>{r.blocked}</td>
                  <td style={{ textAlign: 'center', padding: '8px' }}>
                    {r.ownedDomains > 0 ? <span style={{ color: 'var(--green)' }}>{r.ownedDomains} owned</span> : null}
                    {r.ownedDomains > 0 && r.escalationDomains > 0 ? ' · ' : ''}
                    {r.escalationDomains > 0 ? <span style={{ color: 'var(--orange)' }}>{r.escalationDomains} esc.</span> : null}
                    {r.ownedDomains === 0 && r.escalationDomains === 0 ? <span style={{ color: 'var(--muted)' }}>—</span> : null}
                  </td>
                  <td style={{ textAlign: 'center', padding: '8px' }}>
                    {r.driving > 0 ? (
                      <span style={{ color: r.completionRate > 0.5 ? 'var(--green)' : r.completionRate > 0 ? 'var(--orange)' : 'var(--muted)' }}>
                        {fmtPct(r.completionRate)}
                      </span>
                    ) : <span style={{ color: 'var(--muted)' }}>—</span>}
                  </td>
                  <td style={{ padding: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ flex: 1, height: 14, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden', display: 'flex' }}>
                        <div style={{
                          width: `${(r.activeDriving / maxLoad) * 100}%`,
                          background: r.activeDriving > 5 ? '#ef4444' : '#3b82f6',
                          height: '100%',
                        }} title={`Driving: ${r.activeDriving}`} />
                        <div style={{
                          width: `${(r.activeExecuting / maxLoad) * 100}%`,
                          background: '#10b981',
                          height: '100%',
                        }} title={`Executing: ${r.activeExecuting}`} />
                      </div>
                      <span style={{ fontSize: 11, minWidth: 20, textAlign: 'right', color: r.isOverloaded ? 'var(--red)' : 'var(--muted)' }}>{r.totalLoad}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: '#3b82f6', borderRadius: 2, display: 'inline-block' }} /> Driving
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: '#10b981', borderRadius: 2, display: 'inline-block' }} /> Executing
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: '#ef4444', borderRadius: 2, display: 'inline-block' }} /> Overloaded (&gt;5 driving)
          </span>
          <span>Active/Total shown in table</span>
        </div>
      </section>

      {/* Department Heatmap */}
      {deptHeatmap.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Department Decision Health</strong>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Department</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Total</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Active</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Blocked</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>No Driver</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Stale</th>
                  <th style={{ textAlign: 'center', padding: '6px 8px' }}>Health</th>
                </tr>
              </thead>
              <tbody>
                {deptHeatmap.map(row => {
                  const issues = row.blocked + row.noDriver + row.stale
                  const health = row.active > 0 ? Math.max(0, 1 - issues / row.active) : 1
                  const healthColor = health >= 0.8 ? 'var(--green)' : health >= 0.5 ? 'var(--orange)' : 'var(--red)'
                  return (
                    <tr key={row.dept} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px', fontWeight: 500 }}>{row.dept}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px' }}>{row.total}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px' }}>{row.active}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px', color: row.blocked > 0 ? 'var(--red)' : 'var(--muted)' }}>{row.blocked}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px', color: row.noDriver > 0 ? 'var(--red)' : 'var(--muted)' }}>{row.noDriver}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px', color: row.stale > 0 ? 'var(--orange)' : 'var(--muted)' }}>{row.stale}</td>
                      <td style={{ textAlign: 'center', padding: '6px 8px' }}>
                        <span style={{ fontWeight: 700, color: healthColor }}>{fmtPct(health)}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* Unowned Members */}
      {roleLoadData.filter(r => r.totalLoad === 0 && (r.ownedDomains > 0 || r.escalationDomains > 0)).length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Domain Owners with No Active Decisions</strong>
          </div>
          <div className="stack-list compact">
            {roleLoadData.filter(r => r.totalLoad === 0 && (r.ownedDomains > 0 || r.escalationDomains > 0)).map(r => (
              <div key={r.member.id} className="list-item status-muted">
                <div className="item-head">
                  <strong>{r.member.name}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-muted">{r.ownedDomains} domain{r.ownedDomains !== 1 ? 's' : ''}</span>
                    <span className="badge badge-muted">0 active decisions</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  )
}

// ═══════════════════════════════════════════════════════
// VIEW 6: Leadership DECI Matrix
// ═══════════════════════════════════════════════════════
const MATRIX_ROLE_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  D: { bg: 'rgba(59,130,246,0.2)', fg: '#60a5fa', border: 'rgba(59,130,246,0.4)' },
  E: { bg: 'rgba(16,185,129,0.2)', fg: '#34d399', border: 'rgba(16,185,129,0.4)' },
  C: { bg: 'rgba(245,158,11,0.2)', fg: '#fbbf24', border: 'rgba(245,158,11,0.4)' },
  I: { bg: 'rgba(107,114,128,0.15)', fg: '#9ca3af', border: 'rgba(107,114,128,0.3)' },
}

const MATRIX_ROLE_TOOLTIPS: Record<string, string> = {
  D: 'DRIVER — Owns the decision. Single point of accountability.',
  E: 'EXECUTOR — Implements and delivers the decision.',
  C: 'CONTRIBUTOR — Provides input before the decision is made.',
  I: 'INFORMED — Notified of the outcome. No input required.',
}

const MATRIX_CATEGORY_LABELS: Record<string, string> = {
  product: 'Product & Engineering',
  manufacturing: 'Manufacturing',
  operations: 'Operations',
  marketing: 'Marketing',
  cx: 'Customer Experience',
  commercial: 'Pricing & Commercial',
  executive: 'Executive',
}

const MATRIX_CATEGORY_ORDER = ['product', 'manufacturing', 'operations', 'marketing', 'cx', 'commercial', 'executive']

function LeadershipMatrixView({ team, domains, decisions, onOpenDetail, onReload }: {
  team: DeciTeamMember[]
  domains: DeciDomain[]
  decisions: DeciDecision[]
  onOpenDetail: (id: string) => void
  onReload: () => void
}) {
  const { user } = useAuth()
  const canEdit = user?.email === 'joseph@spidergrills.com'

  const [matrix, setMatrix] = useState<DeciMatrixResponse | null>(null)
  const [matrixLoading, setMatrixLoading] = useState(true)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [createFromRow, setCreateFromRow] = useState<{ domainId: number; name: string } | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [newPriority, setNewPriority] = useState<DeciPriority>('medium')
  const [creating, setCreating] = useState(false)
  const [hoveredCell, setHoveredCell] = useState<{ row: string; memberId: string; role: string } | null>(null)
  const [saving, setSaving] = useState<string | null>(null)  // domain_id being saved
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null) // domain_id pending delete

  const ROLE_CYCLE: (string | null)[] = ['D', 'E', 'C', 'I', null]

  const loadMatrix = useCallback(async () => {
    setMatrixLoading(true)
    try {
      const m = await api.deciMatrix()
      setMatrix(m)
    } catch { /* ignore */ }
    finally { setMatrixLoading(false) }
  }, [])

  /** Silent matrix refresh — no loading spinner, no scroll reset */
  const silentLoadMatrix = useCallback(async () => {
    try {
      const m = await api.deciMatrix()
      setMatrix(m)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { void loadMatrix() }, [loadMatrix])

  // Ownership conflict detector: decisions where driver deviates from matrix default
  const conflicts = useMemo(() => {
    if (!matrix) return []
    const result: { decision: DeciDecision; domain: string; expectedDriver: string; actualDriver: string }[] = []
    for (const d of decisions) {
      if (!d.domain_id || !d.driver_id || d.status === 'complete') continue
      for (const rows of Object.values(matrix.categories)) {
        const row = rows.find(r => r.domain_id === d.domain_id)
        if (row) {
          const expectedEntry = Object.entries(row.assignments).find(([, role]) => role === 'D')
          if (expectedEntry && d.driver_id !== Number(expectedEntry[0])) {
            const expectedName = matrix.members.find(m => m.id === Number(expectedEntry[0]))?.name ?? 'Unknown'
            result.push({ decision: d, domain: row.name, expectedDriver: expectedName, actualDriver: d.driver_name || 'Unknown' })
          }
          break
        }
      }
    }
    return result
  }, [decisions, matrix])

  async function handleBootstrap() {
    setBootstrapping(true)
    try {
      await api.deciBootstrap()
      await Promise.all([onReload(), loadMatrix()])
    } finally { setBootstrapping(false) }
  }

  async function handleCreateFromDomain() {
    if (!createFromRow || !newTitle.trim()) return
    setCreating(true)
    try {
      await api.deciCreateDecision({
        title: newTitle.trim(),
        domain_id: createFromRow.domainId,
        type: 'Project',
        priority: newPriority,
      })
      setNewTitle('')
      setNewPriority('medium')
      setCreateFromRow(null)
      await Promise.all([onReload(), silentLoadMatrix()])
    } finally { setCreating(false) }
  }

  /** Cycle a cell's DECI role and persist via deciUpdateDomain.
   *  Optimistic: update local state immediately so the UI stays in place. */
  async function handleCellClick(row: DeciMatrixRow, memberId: number) {
    if (!matrix) return
    const memberIdStr = String(memberId)
    const currentRole = row.assignments[memberIdStr] || null
    const nextIdx = (ROLE_CYCLE.indexOf(currentRole) + 1) % ROLE_CYCLE.length
    const nextRole = ROLE_CYCLE[nextIdx]

    // Build the updated assignment lists from the current row
    let newDriverId: number | null = null
    const newExecutorIds: number[] = []
    const newContributorIds: number[] = []
    const newInformedIds: number[] = []

    for (const m of matrix.members) {
      const mid = m.id
      const role = mid === memberId ? nextRole : (row.assignments[String(mid)] || null)
      if (role === 'D') newDriverId = mid
      else if (role === 'E') newExecutorIds.push(mid)
      else if (role === 'C') newContributorIds.push(mid)
      else if (role === 'I') newInformedIds.push(mid)
    }

    // Optimistic local update — mutate matrix state in place so scroll position is preserved
    setMatrix(prev => {
      if (!prev) return prev
      const updated = { ...prev, categories: { ...prev.categories } }
      for (const [cat, rows] of Object.entries(updated.categories)) {
        const idx = rows.findIndex(r => r.domain_id === row.domain_id)
        if (idx !== -1) {
          const newRow = { ...rows[idx], assignments: { ...rows[idx].assignments } }
          if (nextRole) {
            newRow.assignments[memberIdStr] = nextRole
          } else {
            delete newRow.assignments[memberIdStr]
          }
          updated.categories[cat] = [...rows]
          updated.categories[cat][idx] = newRow
          break
        }
      }
      return updated
    })

    setSaving(String(row.domain_id))
    try {
      await api.deciUpdateDomain(row.domain_id, {
        default_driver_id: newDriverId,
        default_executor_ids: newExecutorIds,
        default_contributor_ids: newContributorIds,
        default_informed_ids: newInformedIds,
      })
      // Silent background refresh to pick up any server-side changes
      await silentLoadMatrix()
    } catch {
      // Revert on error — re-fetch from server
      await silentLoadMatrix()
    }
    finally { setSaving(null) }
  }

  /** Delete a domain row */
  async function handleDeleteDomain(domainId: number) {
    setSaving(String(domainId))
    try {
      await api.deciDeleteDomain(domainId)
      setConfirmDelete(null)
      // Optimistic: remove the row from local state immediately
      setMatrix(prev => {
        if (!prev) return prev
        const updated = { ...prev, categories: { ...prev.categories } }
        for (const [cat, rows] of Object.entries(updated.categories)) {
          const filtered = rows.filter(r => r.domain_id !== domainId)
          if (filtered.length !== rows.length) {
            updated.categories[cat] = filtered
            break
          }
        }
        return updated
      })
      await Promise.all([onReload(), silentLoadMatrix()])
    } catch {
      await silentLoadMatrix()
    }
    finally { setSaving(null) }
  }

  if (matrixLoading) return <Card title="Loading"><div className="state-message">Loading leadership matrix...</div></Card>

  if (!matrix || matrix.members.length === 0) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Leadership DECI Matrix</strong></div>
        <div style={{ padding: '24px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>&#9878;</div>
          <p style={{ color: '#e2e8f0', fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
            DECI is a power structure, not a tracking tool.
          </p>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 20, maxWidth: 500, margin: '0 auto 20px' }}>
            Bootstrap the full leadership DECI matrix with 6 team members and 21 decision domains across 7 categories.
            Every decision at Spider Grills will flow through this matrix.
          </p>
          <button className="range-button active" onClick={handleBootstrap} disabled={bootstrapping} style={{ fontSize: 14, padding: '10px 28px' }}>
            {bootstrapping ? 'Bootstrapping Leadership Matrix...' : 'Bootstrap Leadership Matrix'}
          </button>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 12, display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
            <span>Joseph (CEO)</span><span>&middot;</span>
            <span>Kyle (Product)</span><span>&middot;</span>
            <span>Conor (Ops)</span><span>&middot;</span>
            <span>Bailey (Marketing)</span><span>&middot;</span>
            <span>Jeremiah (CX)</span><span>&middot;</span>
            <span>David (Mfg)</span>
          </div>
        </div>
      </section>
    )
  }

  const members = matrix.members
  const sortedCategories = MATRIX_CATEGORY_ORDER
    .filter(cat => matrix.categories[cat]?.length)
    .map(cat => ({ key: cat, label: MATRIX_CATEGORY_LABELS[cat] || cat, rows: matrix.categories[cat] }))
  // Include any categories not in our order list
  for (const [cat, rows] of Object.entries(matrix.categories)) {
    if (!MATRIX_CATEGORY_ORDER.includes(cat) && rows.length > 0) {
      sortedCategories.push({ key: cat, label: MATRIX_CATEGORY_LABELS[cat] || cat, rows })
    }
  }

  const totalDomains = Object.values(matrix.categories).reduce((s, rows) => s + rows.length, 0)
  const totalActiveDecisions = Object.values(matrix.categories).reduce((s, rows) => s + rows.reduce((ss, r) => ss + r.active_decisions, 0), 0)

  return (
    <>
      {/* Matrix Header */}
      <section className="card">
        <div className="venom-panel-head">
          <strong style={{ fontSize: 15 }}>Leadership DECI Matrix</strong>
          <div className="inline-badges">
            <span className="badge badge-neutral">{totalDomains} domains</span>
            <span className="badge badge-good">{totalActiveDecisions} active decisions</span>
            <span className="badge badge-neutral">{members.length} leaders</span>
          </div>
        </div>
        <p style={{ color: 'var(--muted)', fontSize: 12, margin: '4px 0 12px' }}>
          Person-first ownership matrix. Every row defines who Drives, Executes, Contributes, and is Informed for each decision area. Click any <strong style={{ color: '#e2e8f0' }}>cell</strong> to cycle its role (D &rarr; E &rarr; C &rarr; I &rarr; empty). Click the <strong style={{ color: '#e2e8f0' }}>row name</strong> to create a new decision in that domain.
        </p>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {Object.entries(MATRIX_ROLE_COLORS).map(([role, colors]) => (
            <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span style={{
                width: 28, height: 22, borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                background: colors.bg, color: colors.fg, border: `1px solid ${colors.border}`, fontWeight: 800, fontSize: 11,
              }}>{role}</span>
              <span style={{ color: 'var(--muted)' }}>{MATRIX_ROLE_TOOLTIPS[role].split('—')[1]?.trim()}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Ownership Conflict Detector */}
      {conflicts.length > 0 ? (
        <section className="card">
          <div className="venom-panel-head">
            <strong>Ownership Conflicts</strong>
            <span className="badge badge-bad">{conflicts.length} deviation{conflicts.length !== 1 ? 's' : ''} from matrix</span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 8px' }}>
            These active decisions have a Driver that differs from the matrix default. This may indicate an intentional override or an assignment error.
          </p>
          <div className="stack-list compact">
            {conflicts.map((c, i) => (
              <div key={`${c.decision.id}-${i}`} className="list-item status-bad" style={{ cursor: 'pointer' }} onClick={() => onOpenDetail(c.decision.id)}>
                <div className="item-head">
                  <strong>{c.decision.title}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-muted">{c.domain}</span>
                    <span className={`badge ${priorityBadge(c.decision.priority)}`}>{c.decision.priority}</span>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  Matrix says <strong style={{ color: '#60a5fa' }}>{c.expectedDriver}</strong> should drive &rarr; currently assigned to <strong style={{ color: 'var(--orange)' }}>{c.actualDriver}</strong>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Create from domain row */}
      {createFromRow ? (
        <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
          <div className="venom-panel-head">
            <strong>Create Decision: {createFromRow.name}</strong>
            <button className="range-button" onClick={() => { setCreateFromRow(null); setNewTitle('') }}>Cancel</button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 10px' }}>
            DECI assignments will be auto-filled from the leadership matrix for this domain.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 300px' }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Decision Title</label>
              <input type="text" value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="What needs to be decided?" className="deci-input" style={{ width: '100%' }} autoFocus />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Priority</label>
              <select value={newPriority} onChange={e => setNewPriority(e.target.value as DeciPriority)} className="deci-input">
                {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <button className="range-button active" onClick={handleCreateFromDomain} disabled={creating || !newTitle.trim()}>
              {creating ? 'Creating...' : 'Create with Matrix Defaults'}
            </button>
          </div>
        </section>
      ) : null}

      {/* Matrix Tables by Category */}
      {sortedCategories.map(({ key: cat, label, rows }) => (
        <section key={cat} className="card">
          <div className="venom-panel-head">
            <strong style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%', display: 'inline-block',
                background: DOMAIN_CATEGORY_COLORS[cat] || '#6b7280',
              }} />
              {label}
            </strong>
            <span className="venom-panel-hint">{rows.length} decision area{rows.length !== 1 ? 's' : ''}</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 650 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '8px 10px', minWidth: 180 }}>Decision Area</th>
                  {members.map(m => (
                    <th key={m.id} style={{ textAlign: 'center', padding: '8px 6px', minWidth: 80, fontSize: 11 }}>
                      <div style={{ fontWeight: 700, color: '#e2e8f0' }}>{m.name.split(' ')[0]}</div>
                      <div style={{ fontWeight: 400, fontSize: 10, color: 'var(--muted)' }}>{m.role || m.department || ''}</div>
                    </th>
                  ))}
                  <th style={{ textAlign: 'center', padding: '8px 6px', minWidth: 50 }}>Active</th>
                  {canEdit && <th style={{ textAlign: 'center', padding: '8px 4px', width: 36 }}></th>}
                </tr>
              </thead>
              <tbody>
                {rows.map(row => {
                  const isSaving = saving === String(row.domain_id)
                  const isDeletePending = confirmDelete === row.domain_id
                  return (
                    <tr
                      key={row.domain_id}
                      style={{
                        borderBottom: '1px solid rgba(255,255,255,0.06)',
                        transition: 'background 0.15s',
                        opacity: isSaving ? 0.6 : 1,
                        background: isDeletePending ? 'rgba(239,68,68,0.08)' : undefined,
                      }}
                    >
                      <td
                        style={{ padding: '8px 10px', cursor: 'pointer' }}
                        onClick={() => setCreateFromRow({ domainId: row.domain_id, name: row.name })}
                        onMouseEnter={e => { if (!isDeletePending) (e.currentTarget as HTMLElement).style.color = '#60a5fa' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = '' }}
                      >
                        <div style={{ fontWeight: 500 }}>{row.name}</div>
                        {row.description ? <div style={{ fontSize: 11, color: 'var(--muted)', maxWidth: 250, lineHeight: 1.3 }}>{row.description}</div> : null}
                      </td>
                      {members.map(m => {
                        const role = row.assignments[String(m.id)]
                        const colors = role ? MATRIX_ROLE_COLORS[role] : null
                        const isHovered = hoveredCell?.row === row.name && hoveredCell?.memberId === String(m.id)
                        return (
                          <td
                            key={m.id}
                            style={{ textAlign: 'center', padding: '6px', cursor: canEdit ? 'pointer' : 'default' }}
                            onMouseEnter={() => setHoveredCell({ row: row.name, memberId: String(m.id), role: role || '' })}
                            onMouseLeave={() => setHoveredCell(null)}
                            onClick={canEdit ? () => handleCellClick(row, m.id) : undefined}
                          >
                            {role ? (
                              <div
                                style={{
                                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                  width: 32, height: 26, borderRadius: 5,
                                  background: colors!.bg, color: colors!.fg, border: `1px solid ${colors!.border}`,
                                  fontWeight: 800, fontSize: 12, letterSpacing: 0.5,
                                  position: 'relative', transition: 'transform 0.1s',
                                  transform: isHovered ? 'scale(1.15)' : 'scale(1)',
                                }}
                                title={canEdit ? `Click to change. Current: ${m.name} = ${MATRIX_ROLE_TOOLTIPS[role]}` : `${m.name} = ${MATRIX_ROLE_TOOLTIPS[role]}`}
                              >
                                {role}
                                {isHovered ? (
                                  <div style={{
                                    position: 'absolute', bottom: '110%', left: '50%', transform: 'translateX(-50%)',
                                    background: '#1e293b', color: '#e2e8f0', padding: '6px 10px', borderRadius: 6,
                                    fontSize: 11, whiteSpace: 'nowrap', zIndex: 20, boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                                    border: '1px solid rgba(255,255,255,0.1)', pointerEvents: 'none',
                                  }}>
                                    <strong>{m.name}</strong>: {MATRIX_ROLE_TOOLTIPS[role]}
                                    {canEdit && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>Click to change</div>}
                                  </div>
                                ) : null}
                              </div>
                            ) : (
                              <div
                                style={{
                                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                  width: 32, height: 26, borderRadius: 5,
                                  border: isHovered ? '1px dashed rgba(255,255,255,0.3)' : '1px dashed rgba(255,255,255,0.08)',
                                  color: isHovered ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.1)',
                                  fontSize: 14, transition: 'all 0.15s',
                                }}
                                title={canEdit ? `Click to assign ${m.name} a role` : 'No role assigned'}
                              >
                                {canEdit ? '+' : '\u00B7'}
                              </div>
                            )}
                          </td>
                        )
                      })}
                      <td style={{ textAlign: 'center', padding: '6px' }}>
                        {row.active_decisions > 0 ? (
                          <span style={{ color: 'var(--green)', fontWeight: 600 }}>{row.active_decisions}</span>
                        ) : (
                          <span style={{ color: 'var(--muted)' }}>0</span>
                        )}
                      </td>
                      {canEdit && (
                      <td style={{ textAlign: 'center', padding: '4px 2px' }}>
                        {isDeletePending ? (
                          <div style={{ display: 'flex', gap: 2 }}>
                            <button
                              onClick={() => handleDeleteDomain(row.domain_id)}
                              disabled={isSaving}
                              style={{
                                background: 'rgba(239,68,68,0.2)', border: '1px solid rgba(239,68,68,0.5)',
                                color: '#f87171', borderRadius: 4, padding: '2px 6px', fontSize: 10,
                                cursor: 'pointer', fontWeight: 700,
                              }}
                              title="Confirm delete"
                            >
                              {isSaving ? '...' : 'Yes'}
                            </button>
                            <button
                              onClick={() => setConfirmDelete(null)}
                              style={{
                                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)',
                                color: 'var(--muted)', borderRadius: 4, padding: '2px 6px', fontSize: 10,
                                cursor: 'pointer',
                              }}
                              title="Cancel"
                            >
                              No
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDelete(row.domain_id)}
                            style={{
                              background: 'none', border: 'none', color: 'rgba(255,255,255,0.15)',
                              cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '2px 4px',
                              borderRadius: 4, transition: 'color 0.15s',
                            }}
                            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#f87171' }}
                            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.15)' }}
                            title="Delete this decision area"
                          >
                            &times;
                          </button>
                        )}
                      </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      {/* Matrix Coverage Summary */}
      <section className="card">
        <div className="venom-panel-head">
          <strong>Coverage Summary</strong>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>Leader</th>
                <th style={{ textAlign: 'center', padding: '8px 6px' }}>
                  <span style={{ color: MATRIX_ROLE_COLORS.D.fg }}>Driving</span>
                </th>
                <th style={{ textAlign: 'center', padding: '8px 6px' }}>
                  <span style={{ color: MATRIX_ROLE_COLORS.E.fg }}>Executing</span>
                </th>
                <th style={{ textAlign: 'center', padding: '8px 6px' }}>
                  <span style={{ color: MATRIX_ROLE_COLORS.C.fg }}>Contributing</span>
                </th>
                <th style={{ textAlign: 'center', padding: '8px 6px' }}>
                  <span style={{ color: MATRIX_ROLE_COLORS.I.fg }}>Informed</span>
                </th>
                <th style={{ textAlign: 'center', padding: '8px 6px' }}>Total Involved</th>
              </tr>
            </thead>
            <tbody>
              {members.map(m => {
                let dCount = 0, eCount = 0, cCount = 0, iCount = 0
                for (const rows of Object.values(matrix.categories)) {
                  for (const row of rows) {
                    const role = row.assignments[String(m.id)]
                    if (role === 'D') dCount++
                    else if (role === 'E') eCount++
                    else if (role === 'C') cCount++
                    else if (role === 'I') iCount++
                  }
                }
                return (
                  <tr key={m.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ fontWeight: 600 }}>{m.name}</div>
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>{[m.role, m.department].filter(Boolean).join(' · ')}</div>
                    </td>
                    <td style={{ textAlign: 'center', padding: '8px 6px' }}>
                      <span style={{ color: MATRIX_ROLE_COLORS.D.fg, fontWeight: 700 }}>{dCount}</span>
                    </td>
                    <td style={{ textAlign: 'center', padding: '8px 6px' }}>
                      <span style={{ color: MATRIX_ROLE_COLORS.E.fg, fontWeight: 600 }}>{eCount}</span>
                    </td>
                    <td style={{ textAlign: 'center', padding: '8px 6px' }}>
                      <span style={{ color: MATRIX_ROLE_COLORS.C.fg }}>{cCount}</span>
                    </td>
                    <td style={{ textAlign: 'center', padding: '8px 6px' }}>
                      <span style={{ color: MATRIX_ROLE_COLORS.I.fg }}>{iCount}</span>
                    </td>
                    <td style={{ textAlign: 'center', padding: '8px 6px' }}>
                      <span style={{ fontWeight: 600 }}>{dCount + eCount + cCount + iCount}</span>
                      <span style={{ color: 'var(--muted)' }}> / {totalDomains}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
