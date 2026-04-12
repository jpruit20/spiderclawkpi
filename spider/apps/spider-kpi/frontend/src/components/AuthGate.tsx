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
    .replace(/^API error \d+ for \/api\/auth\/(signup|login|resend-verification|logout): ?/, '')
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

function getVerifyParam(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  return params.get('verify')
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<AuthStatusResponse>({ authenticated: false, auth_disabled: false, allowed_domains: [], user: null })
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Check for ?verify= parameter from email verification link redirect
  const verifyParam = getVerifyParam()

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

  // Show verify result message
  useEffect(() => {
    if (!verifyParam) return
    if (verifyParam === 'success') {
      setMessage('Email verified successfully! You can now sign in.')
      setMode('login')
    } else if (verifyParam === 'expired') {
      setError('Verification link has expired. Please request a new one.')
      setMode('login')
    } else if (verifyParam === 'invalid') {
      setError('Invalid verification link.')
      setMode('login')
    }
    // Clean the URL
    if (typeof window !== 'undefined') {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [verifyParam])

  async function logout() {
    setSubmitting(true)
    setError(null)
    setMessage(null)
    try {
      await api.logout()
      await refreshStatus()
      setMode('login')
      setPassword('')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to sign out right now'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSignup(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setMessage(null)

    if (password !== confirmPassword) {
      setError('Passwords do not match')
      setSubmitting(false)
      return
    }

    if (password.length < 12) {
      setError('Password must be at least 12 characters long')
      setSubmitting(false)
      return
    }

    try {
      const response = await api.signup(email, password)
      setMessage(response.detail || 'Check your email for a verification link.')
      setPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to create account'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleLogin(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setMessage(null)

    try {
      const nextStatus = await api.login(email, password)
      setStatus(nextStatus)
      setPassword('')
    } catch (err) {
      setError(formatAuthError(err, 'Unable to sign in'))
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

  const allowedDomains = status.allowed_domains?.length
    ? status.allowed_domains.join(', ')
    : null

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={mode === 'signup' ? handleSignup : handleLogin}>
        <div className="auth-eyebrow">Spider Grills KPI Dashboard</div>
        <h1>{mode === 'signup' ? 'Create account' : 'Sign in'}</h1>
        <p>
          {mode === 'signup'
            ? 'Enter your work email and choose a password to get started.'
            : 'Enter your email and password to access the dashboard.'}
        </p>

        {allowedDomains && mode === 'signup' ? (
          <div className="auth-note">
            Access is restricted to <strong>{allowedDomains}</strong> email addresses.
          </div>
        ) : null}

        <label className="auth-label" htmlFor="dashboard-email">Work email</label>
        <input
          id="dashboard-email"
          className="auth-input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          placeholder="you@company.com"
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
          placeholder={mode === 'signup' ? 'Min 12 characters' : 'Enter password'}
          required
          minLength={mode === 'signup' ? 12 : 1}
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
              placeholder="Re-enter password"
              required
              minLength={12}
            />
          </>
        ) : null}

        {message ? <div className="auth-success">{message}</div> : null}
        {error ? <div className="auth-error">{error}</div> : null}

        <button className="auth-button" type="submit" disabled={submitting || !email.trim() || !password.trim() || (mode === 'signup' && !confirmPassword.trim())}>
          {submitting
            ? (mode === 'signup' ? 'Creating account…' : 'Signing in…')
            : (mode === 'signup' ? 'Create account' : 'Sign in')}
        </button>

        <div className="auth-toggle-row">
          {mode === 'login' ? (
            <button
              type="button"
              className="auth-toggle"
              onClick={() => {
                setMode('signup')
                setPassword('')
                setConfirmPassword('')
                setError(null)
                setMessage(null)
              }}
            >
              Create an account
            </button>
          ) : (
            <button
              type="button"
              className="auth-toggle"
              onClick={() => {
                setMode('login')
                setPassword('')
                setConfirmPassword('')
                setError(null)
                setMessage(null)
              }}
            >
              Back to sign in
            </button>
          )}
          {mode === 'login' ? (
            <button
              type="button"
              className="auth-toggle"
              onClick={async () => {
                if (!email.trim()) {
                  setError('Enter your email address first')
                  return
                }
                setSubmitting(true)
                setError(null)
                setMessage(null)
                try {
                  const response = await api.resendVerification(email)
                  setMessage(response.detail || 'If that account exists, a new verification link has been sent.')
                } catch (err) {
                  setError(formatAuthError(err, 'Unable to resend verification email'))
                } finally {
                  setSubmitting(false)
                }
              }}
              disabled={submitting}
            >
              Resend verification
            </button>
          ) : null}
        </div>
      </form>
    </div>
  )
}
