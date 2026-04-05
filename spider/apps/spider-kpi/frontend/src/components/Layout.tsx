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
        <nav className="nav">
          <NavLink to="/">Executive Overview</NavLink>
          <NavLink to="/commercial">Commercial Performance</NavLink>
          <NavLink to="/support">Support / CX</NavLink>
          <NavLink to="/ux">Website UX / Behavior</NavLink>
          <NavLink to="/issues">Issue Radar</NavLink>
          <NavLink to="/diagnostics">Diagnostics</NavLink>
          <NavLink to="/source-health">Source Health</NavLink>
        </nav>
        <div className="sidebar-foot">kpi.spidergrills.com</div>
      </aside>
      <main className="main-shell">{children}</main>
    </div>
  )
}
