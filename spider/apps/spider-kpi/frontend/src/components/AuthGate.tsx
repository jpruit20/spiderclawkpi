import { FormEvent, useEffect, useState } from 'react'

import { ApiError, api } from '../lib/api'

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [authenticated, setAuthenticated] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let active = true
    api.authStatus()
      .then((status) => {
        if (!active) return
        setAuthenticated(Boolean(status.authenticated))
      })
      .catch(() => {
        if (!active) return
        setAuthenticated(false)
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const status = await api.login(password)
      setAuthenticated(Boolean(status.authenticated))
      setPassword('')
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Unable to unlock dashboard'
      setError(message.replace(/^API error 401 for \/api\/auth\/login: ?/, 'Invalid password. '))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Loading dashboard</h1>
          <p>Checking access…</p>
        </div>
      </div>
    )
  }

  if (authenticated) {
    return <>{children}</>
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-eyebrow">Spider KPI</div>
        <h1>Dashboard locked</h1>
        <p>Enter the visitor password to view the KPI dashboard.</p>
        <label className="auth-label" htmlFor="dashboard-password">Visitor password</label>
        <input
          id="dashboard-password"
          className="auth-input"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          placeholder="Enter password"
          required
        />
        {error ? <div className="auth-error">{error}</div> : null}
        <button className="auth-button" type="submit" disabled={submitting || !password.trim()}>
          {submitting ? 'Unlocking…' : 'Unlock dashboard'}
        </button>
      </form>
    </div>
  )
}
