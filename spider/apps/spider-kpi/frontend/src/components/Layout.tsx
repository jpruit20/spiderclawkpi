import { Link, NavLink } from 'react-router-dom'
import { ReactNode } from 'react'
import spiderGrillsLogo from '../../spider_grills_black_nocircle.avif'
import { useAuth } from './AuthGate'
import { ChatPanel } from './ChatPanel'
import { isViewer, pathInScope } from '../lib/access'

// Lore Ledger is still being shaped — keep it on Joseph's dashboard only
// until it's ready for the wider team. Gate matches App.tsx route guard.
const LORE_LEDGER_OWNER_EMAIL = 'joseph@spidergrills.com'

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const canSeeLoreLedger = (user?.email ?? '').toLowerCase() === LORE_LEDGER_OWNER_EMAIL
  const viewerOnly = isViewer(user)

  // Only render a link if it's inside the user's page_scope. Admins/
  // editors with no scope restriction pass through unchanged; scoped
  // viewers (e.g. external collaborators) only see the routes their
  // invite granted them.
  const scoped = (path: string) => pathInScope(user, path)

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <img src={spiderGrillsLogo} alt="Spider Grills" className="brand-mark-image" />
          </div>
          <div>
            <h1>Spider Grills HQ</h1>
          </div>
        </div>
        <div className="sidebar-summary">
          <small>Keep company pages lean: command, financials, issue risk, and system health. Open divisions from their own routes.</small>
        </div>
        <nav className="nav">
          {scoped('/') || scoped('/deci') || scoped('/revenue') || scoped('/issues') || scoped('/social') || scoped('/system-health') ? (
            <small className="nav-group-label">Company</small>
          ) : null}
          {scoped('/') ? <NavLink to="/">Command Center</NavLink> : null}
          {scoped('/deci') ? <NavLink to="/deci">DECI</NavLink> : null}
          {canSeeLoreLedger && scoped('/lore') ? <NavLink to="/lore">Lore Ledger</NavLink> : null}
          {scoped('/revenue') ? <NavLink to="/revenue">Financial / Revenue</NavLink> : null}
          {scoped('/issues') ? <NavLink to="/issues">Issue Radar</NavLink> : null}
          {canSeeLoreLedger && scoped('/issues/ecrs') ? <NavLink to="/issues/ecrs">ECR Tracker</NavLink> : null}
          {scoped('/social') ? <NavLink to="/social">Social Intelligence</NavLink> : null}
          {scoped('/system-health') ? <NavLink to="/system-health">System Health</NavLink> : null}
          {scoped('/division/customer-experience') || scoped('/division/marketing') || scoped('/division/product-engineering') || scoped('/division/operations') || scoped('/division/production-manufacturing') ? (
            <small className="nav-group-label">Divisions</small>
          ) : null}
          {scoped('/division/customer-experience') ? <NavLink to="/division/customer-experience">Customer Experience</NavLink> : null}
          {scoped('/division/marketing') ? <NavLink to="/division/marketing">Marketing</NavLink> : null}
          {scoped('/division/product-engineering') ? (
            <>
              <NavLink to="/division/product-engineering" end>Product / Engineering</NavLink>
              {scoped('/division/product-engineering/firmware') ? (
                <NavLink to="/division/product-engineering/firmware" style={{ paddingLeft: 28, fontSize: 13 }}>↳ Firmware Hub</NavLink>
              ) : null}
            </>
          ) : null}
          {scoped('/division/operations') ? <NavLink to="/division/operations">Operations</NavLink> : null}
          {scoped('/division/production-manufacturing') ? <NavLink to="/division/production-manufacturing">Production / Manufacturing</NavLink> : null}
          {scoped('/departments') ? <NavLink to="/departments">Division Index</NavLink> : null}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-auth-card">
            <small>Signed in as</small>
            <strong>{user?.email ?? 'Dashboard user'}</strong>
            {viewerOnly ? (
              <small style={{ color: 'var(--muted)', marginTop: 4 }}>View-only access</small>
            ) : null}
            <button type="button" className="sidebar-logout-button" onClick={() => { void logout() }}>
              Sign out
            </button>
          </div>
          <div className="sidebar-foot-domain">kpi.spidergrills.com</div>
        </div>
      </aside>
      <main className="main-shell">{children}</main>
      {/* Chat panel posts to the AI-assistant endpoint (mutation). Hidden
          for viewers since they're read-only and don't have AI access. */}
      {viewerOnly ? null : <ChatPanel />}
    </div>
  )
}
