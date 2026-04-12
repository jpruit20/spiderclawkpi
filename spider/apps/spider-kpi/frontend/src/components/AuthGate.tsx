import { FormEvent, createContext, useContext, useEffect, useMemo, useState } from 'react'

import type { AuthStatusResponse, AuthUserSummary } from '../lib/types'
import { ApiError, api } from '../lib/api'

type AuthMode = 'login' | 'signup'

type AuthContextValue = {
  user: AuthUserSummary | null
  authDisabled: boolean
  refreshStatus: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function formatAuthError(err: unknown, fallback: string) {
  const message = err instanceof ApiError ? err.message : fallback
  return message
    .replace(/^API error \d+ for \/api\/auth\/(login|signup|logout): ?/, '')
    .replace(/^\{"detail":"/i, '')
    .replace(/"\}$/i, '')
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth must be used inside AuthGate')
  }
  return value
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<AuthStatusResponse>({ authenticated: false, auth_disabled: false, allowed_domains: [], user: null })
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function refreshStatus() {
    const nextStatus = await api.authStatus()
    setStatus(nextStatus)
  }

  useEffect(() => {
    let active = true
    api.authStatus()
      .then((nextStatus) => {
        if (!active) return
        setStatus(nextStatus)
      })
      .catch(() => {
        if (!active) return
        setStatus({ authenticated: false, auth_disabled: false, allowed_domains: [], user: null })
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function logout() {
    setSubmitting(true)
    setError(null)
    try {
      await api.logout()
      await refreshStatus()
    } catch (err) {
      setError(formatAuthError(err, 'Unable to sign out right now'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    if (mode === 'signup' && password !== confirmPassword) {
      setSubmitting(false)
      setError('Passwords do not match')
      return
    }

    try {
      const nextStatus = mode === 'signup'
        ? await api.signup(email, password)
        : await api.login(email, password)
      setStatus(nextStatus)
      setPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(formatAuthError(err, mode === 'signup' ? 'Unable to create account' : 'Unable to sign in'))
    } finally {
      setSubmitting(false)
    }
  }

  const contextValue = useMemo<AuthContextValue>(() => ({
    user: status.user ?? null,
    authDisabled: Boolean(status.auth_disabled),
    refreshStatus,
    logout,
  }), [status.user, status.auth_disabled])

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

  if (status.authenticated) {
    return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  }

  const allowedDomains = (status.allowed_domains ?? []).join(', ')

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-eyebrow">Spider KPI</div>
        <h1>{mode === 'signup' ? 'Create dashboard account' : 'Sign in to dashboard'}</h1>
        <p>
          {mode === 'signup'
            ? 'Create an account with your company email to unlock the KPI dashboard.'
            : 'Use your dashboard account to view the KPI dashboard.'}
        </p>
        {allowedDomains ? <div className="auth-note">Allowed domains: {allowedDomains}</div> : null}

        <div className="auth-toggle-row" role="tablist" aria-label="Authentication mode">
          <button type="button" className={`auth-toggle ${mode === 'login' ? 'active' : ''}`} onClick={() => { setMode('login'); setError(null) }}>
            Sign in
          </button>
          <button type="button" className={`auth-toggle ${mode === 'signup' ? 'active' : ''}`} onClick={() => { setMode('signup'); setError(null) }}>
            Create account
          </button>
        </div>

        <label className="auth-label" htmlFor="dashboard-email">Work email</label>
        <input
          id="dashboard-email"
          className="auth-input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete={mode === 'signup' ? 'email' : 'username'}
          placeholder="you@spidergrills.com"
          required
        />

        <label className="auth-label" htmlFor="dashboard-password">Password</label>
        <input
          id="dashboard-password"
          className="auth-input"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
          placeholder={mode === 'signup' ? 'Choose a strong password' : 'Enter password'}
          required
        />

        {mode === 'signup' ? (
          <>
            <label className="auth-label" htmlFor="dashboard-confirm-password">Confirm password</label>
            <input
              id="dashboard-confirm-password"
              className="auth-input"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              placeholder="Repeat password"
              required
            />
            <div className="auth-hint">Minimum 12 characters. Use a passphrase, not something short.</div>
          </>
        ) : null}

        {error ? <div className="auth-error">{error}</div> : null}
        <button className="auth-button" type="submit" disabled={submitting || !email.trim() || !password.trim() || (mode === 'signup' && !confirmPassword.trim())}>
          {submitting ? (mode === 'signup' ? 'Creating account…' : 'Signing in…') : (mode === 'signup' ? 'Create account' : 'Sign in')}
        </button>
      </form>
    </div>
  )
}
