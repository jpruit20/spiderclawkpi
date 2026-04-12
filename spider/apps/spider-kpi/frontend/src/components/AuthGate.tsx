import { FormEvent, createContext, useContext, useEffect, useMemo, useState } from 'react'

import type { AuthStatusResponse, AuthUserSummary } from '../lib/types'
import { ApiError, api } from '../lib/api'

type AuthStep = 'email' | 'code'

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
    .replace(/^API error \d+ for \/api\/auth\/(request-code|verify-code|logout): ?/, '')
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
  const [status, setStatus] = useState<AuthStatusResponse>({ authenticated: false, auth_disabled: false, user: null })
  const [step, setStep] = useState<AuthStep>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
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
        setStatus({ authenticated: false, auth_disabled: false, user: null })
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
      setStep('email')
      setCode('')
      setNotice(null)
    } catch (err) {
      setError(formatAuthError(err, 'Unable to sign out right now'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleEmailSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setNotice(null)

    try {
      const response = await api.requestCode(email)
      setStep('code')
      setNotice(response.message)
    } catch (err) {
      setError(formatAuthError(err, 'Unable to continue right now'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCodeSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const nextStatus = await api.verifyCode(email, code)
      setStatus(nextStatus)
      setCode('')
      setNotice(null)
    } catch (err) {
      setError(formatAuthError(err, 'Unable to verify code'))
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
          <h1>Loading</h1>
          <p>Checking access…</p>
        </div>
      </div>
    )
  }

  if (status.authenticated) {
    return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  }

  return (
    <div className="auth-shell">
      {step === 'email' ? (
        <form className="auth-card" onSubmit={handleEmailSubmit}>
          <h1>Verify your email</h1>
          <p>Enter your work email to receive a one-time access code.</p>

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

          {error ? <div className="auth-error">{error}</div> : null}
          <button className="auth-button" type="submit" disabled={submitting || !email.trim()}>
            {submitting ? 'Sending code…' : 'Send code'}
          </button>
        </form>
      ) : (
        <form className="auth-card" onSubmit={handleCodeSubmit}>
          <h1>Check your email</h1>
          <p>Enter the 6-digit code sent to your inbox.</p>

          <label className="auth-label" htmlFor="dashboard-code">Verification code</label>
          <input
            id="dashboard-code"
            className="auth-input"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            autoComplete="one-time-code"
            placeholder="123456"
            required
          />

          {notice ? <div className="auth-note">{notice}</div> : null}
          {error ? <div className="auth-error">{error}</div> : null}

          <button className="auth-button" type="submit" disabled={submitting || code.trim().length !== 6}>
            {submitting ? 'Verifying…' : 'Verify email'}
          </button>

          <button
            type="button"
            className="auth-toggle"
            onClick={() => {
              setStep('email')
              setCode('')
              setError(null)
              setNotice(null)
            }}
          >
            Use a different email
          </button>
        </form>
      )}
    </div>
  )
}
