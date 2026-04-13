import { Link, NavLink } from 'react-router-dom'
import { ReactNode } from 'react'
import spiderGrillsLogo from '../../spider_grills_black_nocircle.avif'
import { useAuth } from './AuthGate'
import { ChatPanel } from './ChatPanel'

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()

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
          <small className="nav-group-label">Company</small>
          <NavLink to="/">Command Center</NavLink>
          <NavLink to="/deci">DECI</NavLink>
          <NavLink to="/revenue">Financial / Revenue</NavLink>
          <NavLink to="/issues">Issue Radar</NavLink>
          <NavLink to="/social">Social Intelligence</NavLink>
          <NavLink to="/system-health">System Health</NavLink>
          <small className="nav-group-label">Divisions</small>
          <NavLink to="/division/customer-experience">Customer Experience</NavLink>
          <NavLink to="/division/marketing">Marketing</NavLink>
          <NavLink to="/division/product-engineering">Product / Engineering</NavLink>
          <NavLink to="/division/operations">Operations</NavLink>
          <NavLink to="/division/production-manufacturing">Production / Manufacturing</NavLink>
          <NavLink to="/departments">Division Index</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-auth-card">
            <small>Signed in as</small>
            <strong>{user?.email ?? 'Dashboard user'}</strong>
            <button type="button" className="sidebar-logout-button" onClick={() => { void logout() }}>
              Sign out
            </button>
          </div>
          <div className="sidebar-foot-domain">kpi.spidergrills.com</div>
        </div>
      </aside>
      <main className="main-shell">{children}</main>
      <ChatPanel />
    </div>
  )
}
