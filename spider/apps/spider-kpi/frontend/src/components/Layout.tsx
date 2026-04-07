import { Link, NavLink } from 'react-router-dom'
import { ReactNode } from 'react'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">🕷️</div>
          <div>
            <h1>Spider KPI</h1>
            <p>Decision Engine</p>
          </div>
        </div>
        <div className="sidebar-summary">
          <small>Start with the top action, then revenue driver, then friction, then root cause.</small>
        </div>
        <nav className="nav">
          <NavLink to="/">Command Center</NavLink>
          <NavLink to="/revenue">Revenue Engine</NavLink>
          <NavLink to="/friction">Friction Map</NavLink>
          <NavLink to="/issues">Issue Radar</NavLink>
          <NavLink to="/root-cause">Root Cause</NavLink>
          <NavLink to="/system-health">System Health</NavLink>
        </nav>
        <div className="sidebar-foot">kpi.spidergrills.com</div>
      </aside>
      <main className="main-shell">{children}</main>
    </div>
  )
}
